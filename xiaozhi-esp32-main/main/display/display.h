#ifndef DISPLAY_H
#define DISPLAY_H

#include "emoji_collection.h"

#ifndef CONFIG_USE_EMOTE_MESSAGE_STYLE
#define HAVE_LVGL 1
#include <lvgl.h>
#endif

#include <esp_timer.h>
#include <esp_log.h>
#include <esp_pm.h>

#include <string>
#include <chrono>
#include <cstddef>

class Theme {
public:
    Theme(const std::string& name) : name_(name) {}
    virtual ~Theme() = default;

    inline std::string name() const { return name_; }
private:
    std::string name_;
};

enum class TerminalCardKind {
    kPortfolio,
    kAsset,
    kNarrative,
    kEmpty,
};

enum class TerminalCardTone {
    kNeutral,
    kPositive,
    kNegative,
    kWarning,
};

// A bounded, presentation-ready market card. The network/parser layer owns
// validation and formatting; display implementations only arrange the fields.
struct TerminalCard {
    TerminalCardKind kind = TerminalCardKind::kEmpty;
    TerminalCardTone tone = TerminalCardTone::kNeutral;
    std::string status;
    std::string eyebrow;
    std::string title;
    std::string primary;
    std::string change_label;
    std::string change;
    std::string left_label;
    std::string left_value;
    std::string right_label;
    std::string right_value;
    std::string footer;
    size_t page_index = 0;
    size_t page_count = 1;
    bool high_priority_alert = false;
    bool animate_alert = false;
    std::string evidence_id;
};

class Display {
public:
    Display();
    virtual ~Display();

    virtual void SetStatus(const char* status);
    virtual void ShowNotification(const char* notification, int duration_ms = 3000);
    virtual void ShowNotification(const std::string &notification, int duration_ms = 3000);
    virtual void SetEmotion(const char* emotion);
    virtual void SetChatMessage(const char* role, const char* content);
    virtual void SetTerminalCard(const TerminalCard& card);
    virtual void SetTerminalTicker(const char* content);
    virtual void ClearChatMessages();
    virtual void SetTheme(Theme* theme);
    virtual Theme* GetTheme() { return current_theme_; }
    virtual void UpdateStatusBar(bool update_all = false);
    virtual void SetPowerSaveMode(bool on);
    virtual void SetupUI() { 
        setup_ui_called_ = true;
    }

    inline int width() const { return width_; }
    inline int height() const { return height_; }
    inline bool IsSetupUICalled() const { return setup_ui_called_; }

protected:
    int width_ = 0;
    int height_ = 0;
    bool setup_ui_called_ = false;  // Track if SetupUI() has been called

    Theme* current_theme_ = nullptr;

    friend class DisplayLockGuard;
    virtual bool Lock(int timeout_ms = 0) = 0;
    virtual void Unlock() = 0;
};


class DisplayLockGuard {
public:
    DisplayLockGuard(Display *display) : display_(display) {
        if (!display_->Lock(30000)) {
            ESP_LOGE("Display", "Failed to lock display");
        }
    }
    ~DisplayLockGuard() {
        display_->Unlock();
    }

private:
    Display *display_;
};

class NoDisplay : public Display {
private:
    virtual bool Lock(int timeout_ms = 0) override {
        return true;
    }
    virtual void Unlock() override {}
};

#endif
