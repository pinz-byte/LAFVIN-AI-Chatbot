#include "terminal_feed.h"

#include "application.h"
#include "board.h"
#include "display.h"
#include "settings.h"
#include "system_info.h"

#include <algorithm>
#include <cstdint>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>
#include <cJSON.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <nvs.h>


#define TAG "TerminalFeed"

namespace {
constexpr size_t kMaxPayloadBytes = 8192;
constexpr size_t kMaxRows = 12;
constexpr size_t kMaxEvents = 10;
constexpr size_t kMaxCards = 15;
constexpr int kMaxRetrySeconds = 15 * 60;
constexpr int64_t kCacheMinimumWriteUs = 30LL * 60LL * 1000LL * 1000LL;
constexpr const char* kCacheNamespace = "symfeed";

bool ReadNvsString(nvs_handle_t handle, const char* key, size_t max_length,
                   std::string& value) {
    size_t length = 0;
    if (nvs_get_str(handle, key, nullptr, &length) != ESP_OK ||
        length == 0 || length > max_length + 1) {
        return false;
    }
    value.resize(length);
    if (nvs_get_str(handle, key, value.data(), &length) != ESP_OK) {
        value.clear();
        return false;
    }
    while (!value.empty() && value.back() == '\0') {
        value.pop_back();
    }
    return true;
}

uint32_t CardHash(const TerminalCard& card) {
    uint32_t hash = 2166136261u;
    const auto mix = [&hash](const std::string& value) {
        for (const unsigned char ch : value) {
            hash ^= ch;
            hash *= 16777619u;
        }
        hash ^= 0xffu;
        hash *= 16777619u;
    };
    mix(card.status);
    mix(card.eyebrow);
    mix(card.title);
    mix(card.primary);
    mix(card.change_label);
    mix(card.change);
    mix(card.left_label);
    mix(card.left_value);
    mix(card.right_label);
    mix(card.right_value);
    mix(card.footer);
    hash ^= static_cast<uint8_t>(card.kind);
    hash *= 16777619u;
    hash ^= static_cast<uint8_t>(card.tone);
    return hash;
}

bool LoadCachedCard(TerminalCard& card) {
    nvs_handle_t handle = 0;
    if (nvs_open(kCacheNamespace, NVS_READONLY, &handle) != ESP_OK) {
        return false;
    }

    uint8_t kind = 0;
    uint8_t tone = 0;
    uint32_t stored_hash = 0;
    const bool valid =
        nvs_get_u32(handle, "hash", &stored_hash) == ESP_OK && stored_hash != 0 &&
        nvs_get_u8(handle, "kind", &kind) == ESP_OK && kind <= 3 &&
        nvs_get_u8(handle, "tone", &tone) == ESP_OK && tone <= 3 &&
        ReadNvsString(handle, "eye", 32, card.eyebrow) &&
        ReadNvsString(handle, "title", 48, card.title) &&
        ReadNvsString(handle, "primary", 180, card.primary) &&
        ReadNvsString(handle, "clabel", 16, card.change_label) &&
        ReadNvsString(handle, "change", 24, card.change) &&
        ReadNvsString(handle, "llabel", 16, card.left_label) &&
        ReadNvsString(handle, "lvalue", 24, card.left_value) &&
        ReadNvsString(handle, "rlabel", 16, card.right_label) &&
        ReadNvsString(handle, "rvalue", 24, card.right_value) &&
        ReadNvsString(handle, "footer", 48, card.footer);
    nvs_close(handle);
    if (!valid) {
        return false;
    }

    card.kind = static_cast<TerminalCardKind>(kind);
    card.tone = static_cast<TerminalCardTone>(tone);
    card.status = "STALE";
    card.right_label = "CONNECTION";
    card.right_value = "OFFLINE";
    card.footer = "LAST VERIFIED CARD | READ ONLY";
    card.page_index = 0;
    card.page_count = 1;
    return true;
}

bool StoreCachedCard(const TerminalCard& card) {
    nvs_handle_t handle = 0;
    if (nvs_open(kCacheNamespace, NVS_READWRITE, &handle) != ESP_OK) {
        ESP_LOGW(TAG, "Terminal cache unavailable");
        return false;
    }

    const uint32_t hash = CardHash(card);
    uint32_t stored_hash = 0;
    if (nvs_get_u32(handle, "hash", &stored_hash) == ESP_OK && stored_hash == hash) {
        nvs_close(handle);
        return true;
    }

    esp_err_t result = nvs_set_u8(handle, "kind", static_cast<uint8_t>(card.kind));
    if (result == ESP_OK) result = nvs_set_u8(handle, "tone", static_cast<uint8_t>(card.tone));
    if (result == ESP_OK) result = nvs_set_str(handle, "eye", card.eyebrow.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "title", card.title.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "primary", card.primary.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "clabel", card.change_label.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "change", card.change.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "llabel", card.left_label.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "lvalue", card.left_value.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "rlabel", card.right_label.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "rvalue", card.right_value.c_str());
    if (result == ESP_OK) result = nvs_set_str(handle, "footer", card.footer.c_str());
    if (result == ESP_OK) result = nvs_set_u32(handle, "hash", hash);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "Terminal cache write skipped: %s", esp_err_to_name(result));
        return false;
    }
    ESP_LOGI(TAG, "Stored bounded last-known terminal card");
    return true;
}

TerminalCard OfflineCard() {
    TerminalCard card;
    card.kind = TerminalCardKind::kEmpty;
    card.tone = TerminalCardTone::kWarning;
    card.status = "OFFLINE";
    card.eyebrow = "CONNECTION";
    card.title = "APEX TERMINAL";
    card.primary = "Waiting for verified market data";
    card.change_label = "MODE";
    card.change = "DISPLAY";
    card.left_label = "LAST UPDATE";
    card.left_value = "UNAVAILABLE";
    card.right_label = "RETRY";
    card.right_value = "AUTOMATIC";
    card.footer = "NO ORDERS | READ ONLY";
    return card;
}

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

bool IsEventKind(const char* value) {
    if (value == nullptr) {
        return false;
    }
    static constexpr const char* kKinds[] = {
        "TRADE", "RISK", "COUNCIL", "OVERSOLD", "OVERBOUGHT",
        "MOVER_UP", "MOVER_DOWN", "BRIEF", "INFO",
    };
    for (const char* kind : kKinds) {
        if (std::strcmp(value, kind) == 0) {
            return true;
        }
    }
    return false;
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

std::string SignedMoney(double value) {
    return std::string(value >= 0.0 ? "+" : "-") + Money(std::fabs(value));
}

std::string Percent(double value) {
    char buffer[20];
    std::snprintf(buffer, sizeof(buffer), "%+.2f%%", value);
    return buffer;
}

TerminalCardTone ToneFor(double value) {
    if (value > 0.000001) {
        return TerminalCardTone::kPositive;
    }
    if (value < -0.000001) {
        return TerminalCardTone::kNegative;
    }
    return TerminalCardTone::kNeutral;
}

const char* CompactSource(const char* value) {
    if (std::strcmp(value, "LIVE BOOK") == 0) {
        return "BROKER";
    }
    if (std::strcmp(value, "APEX COUNCIL") == 0) {
        return "APEX";
    }
    if (std::strcmp(value, "APEX SLACK") == 0) {
        return "SLACK";
    }
    return value;
}

const char* HumanFreshness(const char* value) {
    if (value != nullptr && std::strcmp(value, "FRESH") == 0) {
        return "CURRENT";
    }
    return value != nullptr ? value : "UNKNOWN";
}

bool IsNews(const char* source, const char* title) {
    return (source != nullptr && (
        std::strcmp(source, "SEEKING ALPHA") == 0 ||
        std::strcmp(source, "ARK INVEST") == 0)) ||
        (title != nullptr && std::strncmp(title, "NEWS ", 5) == 0);
}

std::string PercentOrPending(const cJSON* value) {
    if (cJSON_IsNull(value)) {
        return "PENDING";
    }
    char buffer[20];
    std::snprintf(buffer, sizeof(buffer), "%.1f%%", value->valuedouble);
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
    if (task_handle_ != nullptr) {
        xTaskNotifyGive(task_handle_);
    }
}

void TerminalFeed::NextCard() {
    navigation_delta_.fetch_add(1);
    if (task_handle_ != nullptr) {
        xTaskNotifyGive(task_handle_);
    }
}

void TerminalFeed::PreviousCard() {
    navigation_delta_.fetch_sub(1);
    if (task_handle_ != nullptr) {
        xTaskNotifyGive(task_handle_);
    }
}

void TerminalFeed::RefreshNow() {
    refresh_requested_ = true;
    if (task_handle_ != nullptr) {
        xTaskNotifyGive(task_handle_);
    }
}

void TerminalFeed::TaskEntry(void* argument) {
    static_cast<TerminalFeed*>(argument)->Run();
}

void TerminalFeed::Run() {
    std::vector<TerminalCard> cards;
    size_t current_index = 0;
    bool has_displayed = false;
    bool cards_stale = true;
    int retry_seconds = CONFIG_SYMBIOS_TICKER_REFRESH_SECONDS;
    int64_t next_fetch_us = 0;
    int64_t next_page_us = 0;
    int64_t last_cache_write_us = 0;
    std::vector<std::string> seen_alert_ids;

    TerminalCard cached;
    if (LoadCachedCard(cached)) {
        cards.emplace_back(std::move(cached));
        DisplayCard(cards.front());
        has_displayed = true;
        next_page_us = esp_timer_get_time() +
                       static_cast<int64_t>(CONFIG_SYMBIOS_TICKER_PAGE_SECONDS) * 1000000LL;
        last_cache_write_us = esp_timer_get_time();
        ESP_LOGI(TAG, "Rendered bounded last-known card while network synchronizes");
    }

    while (running_) {
        const int64_t now = esp_timer_get_time();
        int64_t next_wake_us = next_fetch_us;
        if (next_page_us > 0 && (next_wake_us == 0 || next_page_us < next_wake_us)) {
            next_wake_us = next_page_us;
        }
        int64_t wait_ms = next_wake_us <= now ? 1 : (next_wake_us - now) / 1000;
        wait_ms = std::max<int64_t>(1, std::min<int64_t>(wait_ms, 1000));
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(wait_ms));
        if (!running_) {
            break;
        }

        auto& app = Application::GetInstance();
        if (app.GetDeviceState() != kDeviceStateIdle) {
            continue;
        }

        const bool manual_refresh = refresh_requested_.exchange(false);
        if (manual_refresh) {
            next_fetch_us = 0;
        }

        const int64_t active_now = esp_timer_get_time();
        if (next_fetch_us == 0 || active_now >= next_fetch_us) {
            std::vector<TerminalCard> refreshed;
            if (Fetch(refreshed)) {
                cards = std::move(refreshed);
                cards_stale = false;
                retry_seconds = CONFIG_SYMBIOS_TICKER_REFRESH_SECONDS;
                if (!cards.empty()) {
                    current_index %= cards.size();
                    // Replace a boot-time cached/offline card immediately;
                    // do not wait for the carousel interval to expose live data.
                    has_displayed = false;
                    next_page_us = 0;
                    if (last_cache_write_us == 0 ||
                        active_now - last_cache_write_us >= kCacheMinimumWriteUs) {
                        if (StoreCachedCard(cards.front())) {
                            last_cache_write_us = active_now;
                        }
                    }
                }
            } else {
                cards_stale = true;
                retry_seconds = std::min(
                    kMaxRetrySeconds,
                    std::max(CONFIG_SYMBIOS_TICKER_REFRESH_SECONDS, retry_seconds * 2));
                if (cards.empty()) {
                    cards.emplace_back(OfflineCard());
                    current_index = 0;
                    has_displayed = false;
                }
            }
            next_fetch_us = active_now + static_cast<int64_t>(retry_seconds) * 1000000LL;
        }

        const int navigation = navigation_delta_.exchange(0);
        const int64_t display_now = esp_timer_get_time();
        if (!cards.empty()) {
            const bool page_due = next_page_us == 0 || display_now >= next_page_us;
            if (navigation == 0 && !page_due) {
                continue;
            }

            if (navigation != 0) {
                const int size = static_cast<int>(cards.size());
                int target = static_cast<int>(current_index) + navigation;
                target %= size;
                if (target < 0) {
                    target += size;
                }
                current_index = static_cast<size_t>(target);
            } else if (has_displayed) {
                current_index = (current_index + 1) % cards.size();
            }

            TerminalCard card = cards[current_index];
            card.page_index = current_index;
            card.page_count = cards.size();
            if (cards_stale) {
                card.status = "STALE";
                card.right_label = "CONNECTION";
                card.right_value = "OFFLINE";
            }
            if (card.high_priority_alert && !card.evidence_id.empty() &&
                std::find(seen_alert_ids.begin(), seen_alert_ids.end(), card.evidence_id) ==
                    seen_alert_ids.end()) {
                card.animate_alert = true;
                seen_alert_ids.emplace_back(card.evidence_id);
                if (seen_alert_ids.size() > 32) {
                    seen_alert_ids.erase(seen_alert_ids.begin());
                }
            }
            DisplayCard(card);
            has_displayed = true;
            next_page_us = display_now +
                           static_cast<int64_t>(CONFIG_SYMBIOS_TICKER_PAGE_SECONDS) * 1000000LL;
        }
    }
    task_handle_ = nullptr;
    vTaskDelete(nullptr);
}

bool TerminalFeed::Fetch(std::vector<TerminalCard>& cards) {
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
    http->SetHeader("X-Symbios-Protocol", "2");
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
    if (!ParsePayload(payload, cards)) {
        ESP_LOGW(TAG, "Terminal feed payload failed validation");
        return false;
    }
    ESP_LOGI(TAG, "Terminal feed refreshed: %u card(s)", static_cast<unsigned>(cards.size()));
    return true;
}

void TerminalFeed::DisplayCard(const TerminalCard& card) {
    Application::GetInstance().Schedule([card]() {
        if (Application::GetInstance().GetDeviceState() != kDeviceStateIdle) {
            return;
        }
        Board::GetInstance().GetDisplay()->SetTerminalCard(card);
    });
}

bool TerminalFeed::ParsePayload(const std::string& payload, std::vector<TerminalCard>& cards) {
    cards.clear();
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
    if (!cJSON_IsNumber(schema) || (schema->valueint != 1 && schema->valueint != 2) ||
        !IsBoundedString(status, 8) || !IsStatus(status->valuestring) ||
        !IsBoundedString(generated, 40) || !IsBoundedString(received, 40)) {
        cJSON_Delete(root);
        return false;
    }

    const std::string status_text = status->valuestring;

    const cJSON* events = cJSON_GetObjectItemCaseSensitive(root, "events");
    if (events != nullptr) {
        if (!cJSON_IsArray(events) || cJSON_GetArraySize(events) > kMaxEvents) {
            cJSON_Delete(root);
            return false;
        }
        const cJSON* event = nullptr;
        cJSON_ArrayForEach(event, events) {
            const cJSON* id = cJSON_GetObjectItemCaseSensitive(event, "id");
            const cJSON* kind = cJSON_GetObjectItemCaseSensitive(event, "kind");
            const cJSON* priority = cJSON_GetObjectItemCaseSensitive(event, "priority");
            const cJSON* title = cJSON_GetObjectItemCaseSensitive(event, "title");
            const cJSON* body = cJSON_GetObjectItemCaseSensitive(event, "body");
            const cJSON* symbol = cJSON_GetObjectItemCaseSensitive(event, "symbol");
            const cJSON* value = cJSON_GetObjectItemCaseSensitive(event, "value");
            const cJSON* change = cJSON_GetObjectItemCaseSensitive(event, "change_pct");
            const cJSON* metric_label = cJSON_GetObjectItemCaseSensitive(event, "metric_label");
            const cJSON* metric_value = cJSON_GetObjectItemCaseSensitive(event, "metric_value");
            const cJSON* source = cJSON_GetObjectItemCaseSensitive(event, "source");
            const cJSON* source_at = cJSON_GetObjectItemCaseSensitive(event, "source_at");
            const cJSON* expires_at = cJSON_GetObjectItemCaseSensitive(event, "expires_at");
            const cJSON* freshness = cJSON_GetObjectItemCaseSensitive(event, "freshness");
            const bool symbol_valid = symbol == nullptr || cJSON_IsNull(symbol) ||
                                      (cJSON_IsString(symbol) && IsSymbol(symbol->valuestring));
            const bool value_valid = value == nullptr || cJSON_IsNull(value) ||
                                     (cJSON_IsNumber(value) && std::isfinite(value->valuedouble));
            const bool change_valid = change == nullptr || cJSON_IsNull(change) ||
                                      (cJSON_IsNumber(change) && std::isfinite(change->valuedouble));
            const bool metric_valid =
                (metric_label == nullptr && metric_value == nullptr) ||
                (IsBoundedString(metric_label, 16) && IsBoundedString(metric_value, 24));
            if (!cJSON_IsObject(event) || !IsBoundedString(id, 40) ||
                !IsBoundedString(kind, 12) || !IsEventKind(kind->valuestring) ||
                !cJSON_IsNumber(priority) || priority->valueint < 0 || priority->valueint > 100 ||
                !IsBoundedString(title, 48) || !IsBoundedString(body, 180) ||
                !symbol_valid || !value_valid || !change_valid || !metric_valid ||
                !IsBoundedString(source, 24) || !IsBoundedString(source_at, 40) ||
                !IsBoundedString(expires_at, 40) || !IsBoundedString(freshness, 8) ||
                std::strcmp(freshness->valuestring, "FRESH") != 0) {
                cJSON_Delete(root);
                cards.clear();
                return false;
            }

            const std::string kind_text = kind->valuestring;
            const std::string title_text = title->valuestring;
            TerminalCard card;
            card.evidence_id = id->valuestring;
            card.high_priority_alert = priority->valueint >= 90 &&
                                       (kind_text == "TRADE" || kind_text == "RISK");
            card.status = status_text;
            const bool signal = cJSON_IsString(metric_label) && cJSON_IsString(metric_value) &&
                                std::strcmp(metric_label->valuestring, "SIGNAL") == 0;
            const bool signal_status = std::strcmp(source->valuestring, "APEX SIGNAL") == 0 &&
                                       cJSON_IsString(metric_label) &&
                                       std::strcmp(metric_label->valuestring, "STATUS") == 0;
            const bool news = IsNews(source->valuestring, title->valuestring);
            if (kind_text == "TRADE") {
                card.eyebrow = "LIVE BOOK";
                card.tone = TerminalCardTone::kPositive;
            } else if (kind_text == "RISK") {
                card.eyebrow = "RISK";
                card.tone = TerminalCardTone::kWarning;
            } else if (kind_text == "COUNCIL") {
                card.eyebrow = "COUNCIL";
                card.tone = TerminalCardTone::kNeutral;
            } else if (kind_text == "OVERSOLD") {
                card.eyebrow = "OVERSOLD";
                card.tone = TerminalCardTone::kNegative;
            } else if (kind_text == "OVERBOUGHT") {
                card.eyebrow = "OVERBOUGHT";
                card.tone = TerminalCardTone::kWarning;
            } else if (kind_text == "MOVER_UP" || kind_text == "MOVER_DOWN") {
                card.eyebrow = kind_text == "MOVER_UP" ? "TOP GAINER" : "TOP LOSER";
                card.tone = kind_text == "MOVER_UP" ? TerminalCardTone::kPositive
                                                     : TerminalCardTone::kNegative;
            } else if (signal) {
                card.eyebrow = std::string(metric_value->valuestring) + " SIGNAL";
                card.tone = std::strcmp(metric_value->valuestring, "SELL") == 0
                                ? TerminalCardTone::kNegative
                                : TerminalCardTone::kPositive;
            } else if (signal_status && title_text.rfind("BUY SIGNAL", 0) == 0) {
                card.eyebrow = "BUY SIGNALS";
                card.tone = TerminalCardTone::kNeutral;
            } else if (signal_status && title_text.rfind("SELL SIGNAL", 0) == 0) {
                card.eyebrow = "SELL SIGNALS";
                card.tone = TerminalCardTone::kNeutral;
            } else if (title_text == "SIGNAL BOARD") {
                card.eyebrow = "SIGNAL BOARD";
                card.tone = TerminalCardTone::kNeutral;
            } else if (title_text == "MARKET MOVERS") {
                card.eyebrow = "MARKET MOVERS";
                card.tone = TerminalCardTone::kNeutral;
            } else if (title_text == "TECHNICAL EXTREMES") {
                card.eyebrow = "TECHNICAL";
                card.tone = TerminalCardTone::kNeutral;
            } else if (news) {
                card.eyebrow = "MARKET NEWS";
                card.tone = TerminalCardTone::kNeutral;
            } else if (kind_text == "BRIEF" && std::strcmp(source->valuestring, "APEX MARKET") == 0) {
                card.eyebrow = title_text.rfind("MARKET CLOSE", 0) == 0
                                   ? "MARKET CLOSE" : "MARKET CONTEXT";
                card.tone = TerminalCardTone::kNeutral;
            } else {
                card.eyebrow = kind_text == "BRIEF" ? "APEX BRIEFING" : "APEX ALERT";
                card.tone = TerminalCardTone::kNeutral;
            }

            card.title = cJSON_IsString(symbol) ? symbol->valuestring : title->valuestring;
            if (cJSON_IsNumber(value) && cJSON_IsString(symbol)) {
                card.kind = TerminalCardKind::kAsset;
                if (kind_text == "COUNCIL") {
                    char score[24];
                    std::snprintf(score, sizeof(score), "SCORE %.0f", value->valuedouble);
                    card.primary = score;
                } else {
                    card.primary = Money(value->valuedouble);
                }
            } else {
                card.kind = TerminalCardKind::kNarrative;
                card.primary = body->valuestring[0] != '\0' ? body->valuestring : title->valuestring;
            }
            if (cJSON_IsNumber(change)) {
                card.change_label = "CHANGE";
                card.change = Percent(change->valuedouble);
                card.tone = ToneFor(change->valuedouble);
            } else if (cJSON_IsString(metric_label) && cJSON_IsString(metric_value)) {
                card.change_label = metric_label->valuestring;
                card.change = metric_value->valuestring;
            } else {
                card.change_label = "FOCUS";
                card.change = news ? "NEWS" : kind_text;
            }
            card.left_label = "FROM";
            card.left_value = CompactSource(source->valuestring);
            card.right_label = "STATUS";
            card.right_value = HumanFreshness(freshness->valuestring);
            card.footer = "VERIFIED DATA | READ ONLY";
            cards.emplace_back(std::move(card));
        }
    }

    TerminalCard btc_card;
    bool has_btc = false;
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
        btc_card.kind = TerminalCardKind::kAsset;
        btc_card.tone = ToneFor(change->valuedouble);
        btc_card.status = status_text;
        btc_card.eyebrow = "CRYPTO | 24H";
        btc_card.title = "BTC / USD";
        btc_card.primary = Money(price->valuedouble);
        btc_card.change_label = "24H CHANGE";
        btc_card.change = Percent(change->valuedouble);
        btc_card.left_label = "WINDOW";
        btc_card.left_value = "24 HOURS";
        btc_card.right_label = "SOURCE";
        btc_card.right_value = "COINBASE";
        btc_card.footer = "AUTHENTICATED | READ ONLY";
        has_btc = true;
    } else if (!cJSON_IsNull(btc)) {
        cJSON_Delete(root);
        return false;
    }

    const cJSON* apex = cJSON_GetObjectItemCaseSensitive(root, "apex");
    std::string market_phase = "unknown";
    if (cJSON_IsObject(apex)) {
        const cJSON* net_liq = cJSON_GetObjectItemCaseSensitive(apex, "net_liq");
        const cJSON* cash_pct = cJSON_GetObjectItemCaseSensitive(apex, "cash_pct");
        const cJSON* positions = cJSON_GetObjectItemCaseSensitive(apex, "position_count");
        const cJSON* risks = cJSON_GetObjectItemCaseSensitive(apex, "risk_count");
        const cJSON* day_pl_total = cJSON_GetObjectItemCaseSensitive(apex, "day_pl_total");
        const cJSON* day_pl_pct = cJSON_GetObjectItemCaseSensitive(apex, "day_pl_pct");
        const cJSON* source_at = cJSON_GetObjectItemCaseSensitive(apex, "source_at");
        const cJSON* phase = cJSON_GetObjectItemCaseSensitive(apex, "market_phase");
        const bool net_liq_valid = cJSON_IsNull(net_liq) || IsFiniteNumber(net_liq, 0.0);
        const bool cash_valid = cJSON_IsNull(cash_pct) ||
                                (cJSON_IsNumber(cash_pct) && std::isfinite(cash_pct->valuedouble));
        const bool day_total_valid = day_pl_total == nullptr || cJSON_IsNull(day_pl_total) ||
                                     (cJSON_IsNumber(day_pl_total) &&
                                      std::isfinite(day_pl_total->valuedouble));
        const bool day_pct_valid = day_pl_pct == nullptr || cJSON_IsNull(day_pl_pct) ||
                                   (cJSON_IsNumber(day_pl_pct) &&
                                    std::isfinite(day_pl_pct->valuedouble));
        if (!net_liq_valid || !cash_valid || !cJSON_IsNumber(positions) ||
            !day_total_valid || !day_pct_valid ||
            positions->valueint < 0 || positions->valueint > 10000 ||
            !cJSON_IsNumber(risks) || risks->valueint < 0 || risks->valueint > 10000 ||
            !IsBoundedString(source_at, 40) ||
            (phase != nullptr && !IsBoundedString(phase, 12))) {
            cJSON_Delete(root);
            return false;
        }
        TerminalCard card;
        if (cJSON_IsString(phase)) {
            market_phase = phase->valuestring;
        }
        const bool last_close = market_phase == "eod" || market_phase == "closed" ||
                                market_phase == "weekend";
        card.kind = TerminalCardKind::kPortfolio;
        card.status = status_text;
        card.eyebrow = "YOUR ACCOUNT";
        card.title = last_close ? "PORTFOLIO | LAST CLOSE" : "SCHWAB PORTFOLIO";
        card.primary = cJSON_IsNull(net_liq) ? "PENDING" : Money(net_liq->valuedouble);
        card.change_label = last_close ? "SESSION P/L" : "TODAY";
        if (cJSON_IsNumber(day_pl_pct)) {
            card.change = Percent(day_pl_pct->valuedouble);
            card.tone = ToneFor(day_pl_pct->valuedouble);
        } else if (cJSON_IsNumber(day_pl_total)) {
            card.change = SignedMoney(day_pl_total->valuedouble);
            card.tone = ToneFor(day_pl_total->valuedouble);
        } else {
            card.change = "N/A";
            card.tone = TerminalCardTone::kNeutral;
        }
        card.left_label = "CASH";
        card.left_value = PercentOrPending(cash_pct);
        card.right_label = last_close ? "MARKET" : "POSITIONS / RISKS";
        char counts[24];
        std::snprintf(counts, sizeof(counts), "%d / %d", positions->valueint, risks->valueint);
        card.right_value = last_close
                               ? (market_phase == "weekend" ? "WEEKEND" : "CLOSED")
                               : counts;
        card.footer = last_close ? "LAST VERIFIED CLOSE | READ ONLY"
                                 : "DIRECT FROM SCHWAB | READ ONLY";
        const size_t portfolio_index = cards.empty() ? 0 : 1;
        cards.insert(cards.begin() + portfolio_index, std::move(card));
    } else if (!cJSON_IsNull(apex)) {
        cJSON_Delete(root);
        return false;
    }

    if (has_btc) {
        cards.emplace_back(std::move(btc_card));
    }

    const cJSON* rows = cJSON_GetObjectItemCaseSensitive(root, "rows");
    if (!cJSON_IsArray(rows) || cJSON_GetArraySize(rows) > kMaxRows) {
        cJSON_Delete(root);
        return false;
    }
    const cJSON* row = nullptr;
    cJSON_ArrayForEach(row, rows) {
        const cJSON* symbol = cJSON_GetObjectItemCaseSensitive(row, "symbol");
        const cJSON* price = cJSON_GetObjectItemCaseSensitive(row, "price");
        const cJSON* kind = cJSON_GetObjectItemCaseSensitive(row, "kind");
        const cJSON* change = cJSON_GetObjectItemCaseSensitive(row, "change_pct");
        const cJSON* source_at = cJSON_GetObjectItemCaseSensitive(row, "source_at");
        const bool change_valid = change == nullptr || cJSON_IsNull(change) ||
                                  (cJSON_IsNumber(change) && std::isfinite(change->valuedouble));
        if (!cJSON_IsObject(row) || !cJSON_IsString(symbol) || !IsSymbol(symbol->valuestring) ||
            !IsFiniteNumber(price, 0.00000001) || !IsBoundedString(kind, 9) ||
            (std::strcmp(kind->valuestring, "position") != 0 &&
             std::strcmp(kind->valuestring, "watchlist") != 0) ||
            !change_valid ||
            !IsBoundedString(source_at, 40)) {
            cJSON_Delete(root);
            cards.clear();
            return false;
        }
        const bool is_position = std::strcmp(kind->valuestring, "position") == 0;
        TerminalCard card;
        card.kind = TerminalCardKind::kAsset;
        card.status = status_text;
        card.eyebrow = is_position ? "POSITION" : "WATCHLIST";
        card.title = symbol->valuestring;
        card.primary = Money(price->valuedouble);
        card.change_label = "CHANGE";
        if (cJSON_IsNumber(change)) {
            card.change = Percent(change->valuedouble);
            card.tone = ToneFor(change->valuedouble);
        } else {
            card.change = "N/A";
            card.tone = TerminalCardTone::kNeutral;
        }
        card.left_label = "IN";
        card.left_value = is_position ? "PORTFOLIO" : "WATCHLIST";
        card.right_label = "QUOTE";
        const bool last_close = market_phase == "eod" || market_phase == "closed" ||
                                market_phase == "weekend";
        card.right_value = last_close ? "LAST CLOSE"
                                      : (status_text == "LIVE" ? "CURRENT" : status_text);
        card.footer = last_close ? "LAST VERIFIED CLOSE | READ ONLY"
                                 : "SCHWAB QUOTE | READ ONLY";
        if (cards.size() < kMaxCards) {
            cards.emplace_back(std::move(card));
        }
    }

    if (cards.empty()) {
        TerminalCard card;
        card.kind = TerminalCardKind::kEmpty;
        card.tone = TerminalCardTone::kWarning;
        card.status = status_text;
        card.eyebrow = "TERMINAL";
        card.title = "APEX DATA";
        card.primary = "PENDING";
        card.change_label = "AVAILABILITY";
        card.change = "NO DATA";
        card.left_label = "MODE";
        card.left_value = "DISPLAY";
        card.right_label = "MARKET FEED";
        card.right_value = status_text;
        card.footer = "AUTHENTICATED | READ ONLY";
        cards.emplace_back(std::move(card));
    }
    for (size_t index = 0; index < cards.size(); ++index) {
        cards[index].page_index = index;
        cards[index].page_count = cards.size();
    }
    cJSON_Delete(root);
    return cards.size() <= kMaxCards;
}
