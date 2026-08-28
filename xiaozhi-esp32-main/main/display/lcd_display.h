#ifndef LCD_DISPLAY_H
#define LCD_DISPLAY_H

#include "lvgl_display.h"
#include "gif/lvgl_gif.h"

#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <font_emoji.h>

#include <atomic>
#include <array>
#include <cstdint>
#include <memory>

#define PREVIEW_IMAGE_DURATION_MS 5000


class LcdDisplay : public LvglDisplay {
protected:
    esp_lcd_panel_io_handle_t panel_io_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;
    
    lv_draw_buf_t draw_buf_;
    lv_obj_t* top_bar_ = nullptr;
    lv_obj_t* status_bar_ = nullptr;
    lv_obj_t* content_ = nullptr;
    lv_obj_t* container_ = nullptr;
    lv_obj_t* side_bar_ = nullptr;
    lv_obj_t* bottom_bar_ = nullptr;
    lv_obj_t* preview_image_ = nullptr;
    lv_obj_t* emoji_label_ = nullptr;
    lv_obj_t* emoji_image_ = nullptr;
    std::unique_ptr<LvglGif> gif_controller_ = nullptr;
    lv_obj_t* emoji_box_ = nullptr;
    lv_obj_t* chat_message_label_ = nullptr;
    lv_obj_t* ticker_panel_ = nullptr;
    lv_obj_t* ticker_brand_label_ = nullptr;
    lv_obj_t* ticker_time_label_ = nullptr;
    lv_obj_t* ticker_status_chip_ = nullptr;
    lv_obj_t* ticker_status_label_ = nullptr;
    lv_obj_t* ticker_status_rule_ = nullptr;
    lv_obj_t* ticker_stamp_ = nullptr;
    lv_obj_t* ticker_eyebrow_label_ = nullptr;
    lv_obj_t* ticker_title_label_ = nullptr;
    lv_obj_t* ticker_primary_label_ = nullptr;
    lv_obj_t* ticker_change_chip_ = nullptr;
    lv_obj_t* ticker_change_caption_ = nullptr;
    lv_obj_t* ticker_change_label_ = nullptr;
    lv_obj_t* ticker_left_card_ = nullptr;
    lv_obj_t* ticker_left_label_ = nullptr;
    lv_obj_t* ticker_left_value_ = nullptr;
    lv_obj_t* ticker_right_card_ = nullptr;
    lv_obj_t* ticker_right_label_ = nullptr;
    lv_obj_t* ticker_right_value_ = nullptr;
    lv_obj_t* ticker_footer_label_ = nullptr;
    lv_obj_t* ticker_page_label_ = nullptr;
    lv_obj_t* ticker_page_rule_ = nullptr;
    lv_obj_t* ticker_alert_frame_ = nullptr;
#if CONFIG_SYMBIOS_TERMINAL_TICKER
    std::array<uint16_t, 104 * 22> ticker_stamp_buffer_{};
#endif
    esp_timer_handle_t preview_timer_ = nullptr;
    std::unique_ptr<LvglImage> preview_image_cached_ = nullptr;
    bool hide_subtitle_ = false;  // Control whether to hide chat messages/subtitles

    void InitializeLcdThemes();
    virtual bool Lock(int timeout_ms = 0) override;
    virtual void Unlock() override;

protected:
    // Add protected constructor
    LcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel, int width, int height);
    
public:
    ~LcdDisplay();
    virtual void SetEmotion(const char* emotion) override;
    virtual void SetChatMessage(const char* role, const char* content) override;
    virtual void SetTerminalCard(const TerminalCard& card) override;
    virtual void SetTerminalTicker(const char* content) override;
    virtual void ClearChatMessages() override;
    virtual void SetPreviewImage(std::unique_ptr<LvglImage> image) override;
    virtual void SetupUI() override;
    // Add theme switching function
    virtual void SetTheme(Theme* theme) override;
    
    // Set whether to hide chat messages/subtitles
    void SetHideSubtitle(bool hide);
};

// SPI LCD display
class SpiLcdDisplay : public LcdDisplay {
public:
    SpiLcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel,
                  int width, int height, int offset_x, int offset_y,
                  bool mirror_x, bool mirror_y, bool swap_xy);
};

// RGB LCD display
class RgbLcdDisplay : public LcdDisplay {
public:
    RgbLcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel,
                  int width, int height, int offset_x, int offset_y,
                  bool mirror_x, bool mirror_y, bool swap_xy);
};

// MIPI LCD display
class MipiLcdDisplay : public LcdDisplay {
public:
    MipiLcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel,
                   int width, int height, int offset_x, int offset_y,
                   bool mirror_x, bool mirror_y, bool swap_xy);
};

#endif // LCD_DISPLAY_H
