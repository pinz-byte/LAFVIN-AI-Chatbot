#include "terminal_feed.h"

#include "application.h"
#include "board.h"
#include "display.h"
#include "settings.h"
#include "system_info.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <cJSON.h>
#include <esp_log.h>


#define TAG "TerminalFeed"

namespace {
constexpr size_t kMaxPayloadBytes = 4096;
constexpr size_t kMaxRows = 6;

bool IsStatus(const char* value) {
    return value != nullptr && (
        std::strcmp(value, "LIVE") == 0 ||
        std::strcmp(value, "DELAYED") == 0 ||
        std::strcmp(value, "STALE") == 0 ||
        std::strcmp(value, "OFFLINE") == 0);
}

bool IsSymbol(const char* value) {
    if (value == nullptr) {
        return false;
    }
    const size_t length = std::strlen(value);
    if (length == 0 || length > 12) {
        return false;
    }
    for (size_t i = 0; i < length; ++i) {
        const char ch = value[i];
        if (!((ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '.' || ch == '-')) {
            return false;
        }
    }
    return true;
}

bool IsBoundedString(const cJSON* item, size_t max_length) {
    return cJSON_IsString(item) && item->valuestring != nullptr &&
           std::strlen(item->valuestring) <= max_length;
}

bool IsFiniteNumber(const cJSON* item, double minimum) {
    return cJSON_IsNumber(item) && std::isfinite(item->valuedouble) &&
           item->valuedouble >= minimum;
}

std::string Money(double value) {
    char buffer[24];
    const double absolute = std::fabs(value);
    if (absolute >= 1000000.0) {
        std::snprintf(buffer, sizeof(buffer), "$%.2fM", value / 1000000.0);
    } else if (absolute >= 1000.0) {
        std::snprintf(buffer, sizeof(buffer), "$%.1fK", value / 1000.0);
    } else if (absolute >= 100.0) {
        std::snprintf(buffer, sizeof(buffer), "$%.2f", value);
    } else {
        std::snprintf(buffer, sizeof(buffer), "$%.3g", value);
    }
    return buffer;
}
}  // namespace


TerminalFeed::~TerminalFeed() {
    Stop();
}

void TerminalFeed::Start() {
    if (running_.exchange(true)) {
        return;
    }
    const BaseType_t created = xTaskCreate(
        TaskEntry,
        "terminal_feed",
        7 * 1024,
        this,
        1,
        &task_handle_);
    if (created != pdPASS) {
        running_ = false;
        task_handle_ = nullptr;
        ESP_LOGE(TAG, "Could not start terminal feed task");
    }
}

void TerminalFeed::Stop() {
    running_ = false;
}

void TerminalFeed::TaskEntry(void* argument) {
    static_cast<TerminalFeed*>(argument)->Run();
}

void TerminalFeed::Run() {
    std::vector<std::string> pages;
    size_t page_index = 0;
    int seconds_until_fetch = 10;

    while (running_) {
        vTaskDelay(pdMS_TO_TICKS(CONFIG_SYMBIOS_TICKER_PAGE_SECONDS * 1000));
        if (!running_) {
            break;
        }
        seconds_until_fetch -= CONFIG_SYMBIOS_TICKER_PAGE_SECONDS;

        auto& app = Application::GetInstance();
        if (app.GetDeviceState() != kDeviceStateIdle) {
            continue;
        }

        if (pages.empty() || seconds_until_fetch <= 0) {
            std::vector<std::string> refreshed;
            if (Fetch(refreshed)) {
                pages = std::move(refreshed);
                page_index = 0;
            }
            seconds_until_fetch = CONFIG_SYMBIOS_TICKER_REFRESH_SECONDS;
        }
        if (!pages.empty()) {
            DisplayPage(pages[page_index % pages.size()]);
            page_index = (page_index + 1) % pages.size();
        }
    }
    task_handle_ = nullptr;
    vTaskDelete(nullptr);
}

bool TerminalFeed::Fetch(std::vector<std::string>& pages) {
    Settings settings("symbios", false);
    const std::string token = settings.GetString("device_token");
    if (token.size() < 32) {
        ESP_LOGW(TAG, "Terminal feed waiting for device enrollment");
        return false;
    }

    auto& board = Board::GetInstance();
    auto http = board.GetNetwork()->CreateHttp(0);
    http->SetHeader("Authorization", "Device " + token);
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress());
    http->SetHeader("Client-Id", board.GetUuid());
    http->SetHeader("Accept", "application/json");
    http->SetHeader("X-Symbios-Protocol", "1");
    if (!http->Open("GET", CONFIG_SYMBIOS_TERMINAL_FEED_URL)) {
        ESP_LOGW(TAG, "Terminal feed connection failed");
        return false;
    }
    const int status = http->GetStatusCode();
    const size_t content_length = http->GetBodyLength();
    if (status != 200 || content_length > kMaxPayloadBytes) {
        ESP_LOGW(TAG, "Terminal feed rejected response status=%d bytes=%u",
                 status, static_cast<unsigned>(content_length));
        http->Close();
        return false;
    }
    std::string payload = http->ReadAll();
    http->Close();
    if (payload.size() > kMaxPayloadBytes) {
        ESP_LOGW(TAG, "Terminal feed response exceeded bound");
        return false;
    }
    if (!ParsePayload(payload, pages)) {
        ESP_LOGW(TAG, "Terminal feed payload failed validation");
        return false;
    }
    ESP_LOGI(TAG, "Terminal feed refreshed: %u page(s)", static_cast<unsigned>(pages.size()));
    return true;
}

void TerminalFeed::DisplayPage(const std::string& page) {
    Application::GetInstance().Schedule([page]() {
        if (Application::GetInstance().GetDeviceState() != kDeviceStateIdle) {
            return;
        }
        Board::GetInstance().GetDisplay()->SetTerminalTicker(page.c_str());
    });
}

bool TerminalFeed::ParsePayload(const std::string& payload, std::vector<std::string>& pages) {
    pages.clear();
    if (payload.empty() || payload.size() > kMaxPayloadBytes) {
        return false;
    }
    cJSON* root = cJSON_ParseWithLength(payload.data(), payload.size());
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return false;
    }

    const cJSON* schema = cJSON_GetObjectItemCaseSensitive(root, "schema_version");
    const cJSON* status = cJSON_GetObjectItemCaseSensitive(root, "status");
    const cJSON* generated = cJSON_GetObjectItemCaseSensitive(root, "generated_at");
    const cJSON* received = cJSON_GetObjectItemCaseSensitive(root, "received_at");
    if (!cJSON_IsNumber(schema) || schema->valueint != 1 ||
        !IsBoundedString(status, 8) || !IsStatus(status->valuestring) ||
        !IsBoundedString(generated, 40) || !IsBoundedString(received, 40)) {
        cJSON_Delete(root);
        return false;
    }

    const cJSON* btc = cJSON_GetObjectItemCaseSensitive(root, "btc");
    if (cJSON_IsObject(btc)) {
        const cJSON* symbol = cJSON_GetObjectItemCaseSensitive(btc, "symbol");
        const cJSON* price = cJSON_GetObjectItemCaseSensitive(btc, "price");
        const cJSON* change = cJSON_GetObjectItemCaseSensitive(btc, "change_24h_pct");
        const cJSON* source_at = cJSON_GetObjectItemCaseSensitive(btc, "source_at");
        if (!cJSON_IsString(symbol) || std::strcmp(symbol->valuestring, "BTC-USD") != 0 ||
            !IsFiniteNumber(price, 0.00000001) || !cJSON_IsNumber(change) ||
            !std::isfinite(change->valuedouble) || !IsBoundedString(source_at, 40)) {
            cJSON_Delete(root);
            return false;
        }
        char page[96];
        std::snprintf(page, sizeof(page), "%s  BTC %s\n%+.2f%% / 24h",
                      status->valuestring, Money(price->valuedouble).c_str(), change->valuedouble);
        pages.emplace_back(page);
    } else if (!cJSON_IsNull(btc)) {
        cJSON_Delete(root);
        return false;
    }

    const cJSON* apex = cJSON_GetObjectItemCaseSensitive(root, "apex");
    if (cJSON_IsObject(apex)) {
        const cJSON* net_liq = cJSON_GetObjectItemCaseSensitive(apex, "net_liq");
        const cJSON* cash_pct = cJSON_GetObjectItemCaseSensitive(apex, "cash_pct");
        const cJSON* positions = cJSON_GetObjectItemCaseSensitive(apex, "position_count");
        const cJSON* risks = cJSON_GetObjectItemCaseSensitive(apex, "risk_count");
        const cJSON* source_at = cJSON_GetObjectItemCaseSensitive(apex, "source_at");
        const bool net_liq_valid = cJSON_IsNull(net_liq) || IsFiniteNumber(net_liq, 0.0);
        const bool cash_valid = cJSON_IsNull(cash_pct) ||
                                (cJSON_IsNumber(cash_pct) && std::isfinite(cash_pct->valuedouble));
        if (!net_liq_valid || !cash_valid || !cJSON_IsNumber(positions) ||
            positions->valueint < 0 || positions->valueint > 10000 ||
            !cJSON_IsNumber(risks) || risks->valueint < 0 || risks->valueint > 10000 ||
            !IsBoundedString(source_at, 40)) {
            cJSON_Delete(root);
            return false;
        }
        const std::string net_text = cJSON_IsNull(net_liq) ? "PENDING" : Money(net_liq->valuedouble);
        char page[128];
        if (cJSON_IsNull(cash_pct)) {
            std::snprintf(page, sizeof(page), "APEX %s\nNL %s  Cash PENDING\n%d pos  %d risk",
                          status->valuestring, net_text.c_str(), positions->valueint, risks->valueint);
        } else {
            std::snprintf(page, sizeof(page), "APEX %s\nNL %s  Cash %.1f%%\n%d pos  %d risk",
                          status->valuestring, net_text.c_str(), cash_pct->valuedouble,
                          positions->valueint, risks->valueint);
        }
        pages.emplace_back(page);
    } else if (!cJSON_IsNull(apex)) {
        cJSON_Delete(root);
        return false;
    }

    const cJSON* rows = cJSON_GetObjectItemCaseSensitive(root, "rows");
    if (!cJSON_IsArray(rows) || cJSON_GetArraySize(rows) > kMaxRows) {
        cJSON_Delete(root);
        return false;
    }
    std::vector<std::string> row_lines;
    const cJSON* row = nullptr;
    cJSON_ArrayForEach(row, rows) {
        const cJSON* symbol = cJSON_GetObjectItemCaseSensitive(row, "symbol");
        const cJSON* price = cJSON_GetObjectItemCaseSensitive(row, "price");
        const cJSON* kind = cJSON_GetObjectItemCaseSensitive(row, "kind");
        const cJSON* source_at = cJSON_GetObjectItemCaseSensitive(row, "source_at");
        if (!cJSON_IsObject(row) || !cJSON_IsString(symbol) || !IsSymbol(symbol->valuestring) ||
            !IsFiniteNumber(price, 0.00000001) || !IsBoundedString(kind, 9) ||
            (std::strcmp(kind->valuestring, "position") != 0 &&
             std::strcmp(kind->valuestring, "watchlist") != 0) ||
            !IsBoundedString(source_at, 40)) {
            cJSON_Delete(root);
            pages.clear();
            return false;
        }
        row_lines.emplace_back(std::string(symbol->valuestring) + "  " + Money(price->valuedouble));
    }
    for (size_t index = 0; index < row_lines.size(); index += 2) {
        std::string page = status->valuestring;
        page += "  MARKET\n" + row_lines[index];
        if (index + 1 < row_lines.size()) {
            page += "\n" + row_lines[index + 1];
        }
        pages.emplace_back(std::move(page));
    }

    if (pages.empty()) {
        pages.emplace_back(std::string("APEX ") + status->valuestring + "\nNo current market rows");
    }
    cJSON_Delete(root);
    return pages.size() <= 5;
}
