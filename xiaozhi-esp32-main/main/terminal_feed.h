#pragma once

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

    // Public so an ESP-IDF unit-test component can exercise the exact parser.
    static bool ParsePayload(const std::string& payload, std::vector<std::string>& pages);

private:
    static void TaskEntry(void* argument);
    void Run();
    bool Fetch(std::vector<std::string>& pages);
    void DisplayPage(const std::string& page);

    std::atomic<bool> running_{false};
    TaskHandle_t task_handle_ = nullptr;
};
