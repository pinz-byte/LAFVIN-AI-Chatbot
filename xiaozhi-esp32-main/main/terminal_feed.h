#pragma once

#include "display/display.h"

#include <atomic>
#include <string>
#include <vector>

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>


class TerminalFeed {
public:
    TerminalFeed() = default;
    ~TerminalFeed();

    TerminalFeed(const TerminalFeed&) = delete;
    TerminalFeed& operator=(const TerminalFeed&) = delete;

    void Start();
    void Stop();
    void NextCard();
    void PreviousCard();
    void RefreshNow();

    // Public so an ESP-IDF unit-test component can exercise the exact parser.
    static bool ParsePayload(const std::string& payload, std::vector<TerminalCard>& cards);

private:
    static void TaskEntry(void* argument);
    void Run();
    bool Fetch(std::vector<TerminalCard>& cards);
    void DisplayCard(const TerminalCard& card);

    std::atomic<bool> running_{false};
    std::atomic<int> navigation_delta_{0};
    std::atomic<bool> refresh_requested_{false};
    TaskHandle_t task_handle_ = nullptr;
};
