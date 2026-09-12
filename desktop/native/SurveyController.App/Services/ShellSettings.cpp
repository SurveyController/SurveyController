#include "pch.h"
#include "ShellSettings.h"

namespace winrt::SurveyController::App::Services
{
    ShellSettings& ShellSettings::Current()
    {
        static ShellSettings instance;
        return instance;
    }

    hstring ShellSettings::Json() const
    {
        std::scoped_lock lock(m_mutex);
        return m_json;
    }

    void ShellSettings::Update(hstring const& json)
    {
        std::function<void(hstring const&)> handler;
        {
            std::scoped_lock lock(m_mutex);
            m_json = json;
            handler = m_changed;
        }
        if (handler) handler(json);
    }

    void ShellSettings::SetChangedHandler(std::function<void(hstring const&)> handler)
    {
        hstring current;
        bool shouldInvoke = false;
        {
            std::scoped_lock lock(m_mutex);
            m_changed = std::move(handler);
            if (m_changed && !m_json.empty())
            {
                current = m_json;
                shouldInvoke = true;
            }
        }
        if (shouldInvoke) m_changed(current);
    }
}
