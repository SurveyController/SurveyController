#pragma once

#include <functional>
#include <mutex>

namespace winrt::SurveyController::App::Services
{
    class ShellSettings final
    {
    public:
        static ShellSettings& Current();

        hstring Json() const;
        void Update(hstring const& json);
        void SetChangedHandler(std::function<void(hstring const&)> handler);

    private:
        mutable std::mutex m_mutex;
        hstring m_json;
        std::function<void(hstring const&)> m_changed;
    };
}
