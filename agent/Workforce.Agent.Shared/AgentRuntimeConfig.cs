using System.Text.Json;
using System.Text.Json.Serialization;

namespace Workforce.Agent.Shared;

public sealed record WorkScheduleConfig(
    [property: JsonPropertyName("weekdays")] int[] Weekdays,
    [property: JsonPropertyName("start")] string Start,
    [property: JsonPropertyName("end")] string End,
    [property: JsonPropertyName("break_minutes")] int BreakMinutes = 0,
    [property: JsonPropertyName("late_tolerance_minutes")] int LateToleranceMinutes = 5);

public sealed record AgentRuntimeConfig(
    [property: JsonPropertyName("activity_poll_interval_sec")] int ActivityPollIntervalSeconds = 2,
    [property: JsonPropertyName("idle_threshold_sec")] int IdleThresholdSeconds = 300,
    [property: JsonPropertyName("batch_interval_sec")] int BatchIntervalSeconds = 60,
    [property: JsonPropertyName("batch_size")] int BatchSize = 500,
    [property: JsonPropertyName("collect_window_titles")] bool CollectWindowTitles = true,
    [property: JsonPropertyName("collect_browser_urls")] bool CollectBrowserUrls = true,
    [property: JsonPropertyName("personal_time_enabled")] bool PersonalTimeEnabled = true,
    [property: JsonPropertyName("screenshot_enabled")] bool ScreenshotEnabled = true,
    [property: JsonPropertyName("screenshot_interval_sec")] int ScreenshotIntervalSeconds = 300,
    [property: JsonPropertyName("screenshot_random_offset")] bool ScreenshotRandomOffset = true,
    [property: JsonPropertyName("screenshot_all_monitors")] bool ScreenshotAllMonitors = false,
    [property: JsonPropertyName("screenshot_multi_monitor_mode")] string ScreenshotMultiMonitorMode = "merge",
    [property: JsonPropertyName("screenshot_max_long_side")] int ScreenshotMaxLongSide = 1600,
    [property: JsonPropertyName("screenshot_quality")] int ScreenshotQuality = 70,
    [property: JsonPropertyName("screenshot_on_unproductive")] bool ScreenshotOnUnproductive = false,
    [property: JsonPropertyName("screenshot_blur_mode")] string ScreenshotBlurMode = "none",
    [property: JsonPropertyName("private_app_patterns")] string[]? PrivateAppPatterns = null,
    [property: JsonPropertyName("employee_timezone")] string EmployeeTimezone = "UTC",
    [property: JsonPropertyName("work_schedule")] WorkScheduleConfig? WorkSchedule = null,
    [property: JsonPropertyName("holiday_dates")] string[]? HolidayDates = null,
    [property: JsonPropertyName("schedule_grace_minutes")] int ScheduleGraceMinutes = 60,
    [property: JsonPropertyName("collect_outside_schedule_activity")] bool CollectOutsideScheduleActivity = true,
    [property: JsonPropertyName("treat_media_playback_as_activity")] bool TreatMediaPlaybackAsActivity = true,
    [property: JsonPropertyName("video_recording_mode")] string VideoRecordingMode = "on_demand",
    [property: JsonPropertyName("video_profile")] string VideoProfile = "medium",
    [property: JsonPropertyName("video_schedule_windows")] JsonElement[]? VideoScheduleWindows = null,
    [property: JsonPropertyName("video_trigger_minutes")] int VideoTriggerMinutes = 5,
    [property: JsonPropertyName("video_on_demand_timeout_minutes")] int VideoOnDemandTimeoutMinutes = 30,
    [property: JsonPropertyName("privacy_contact")] string PrivacyContact = "Ответственный назначается работодателем",
    [property: JsonPropertyName("privacy_retention_notice")] string PrivacyRetentionNotice = "Сроки хранения задаются политикой организации")
{
    public static string ConfigPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
        "WorkforceMonitoring",
        "agent-config.json");

    public AgentRuntimeConfig Validated() => this with
    {
        ActivityPollIntervalSeconds = Math.Clamp(ActivityPollIntervalSeconds, 1, 5),
        IdleThresholdSeconds = Math.Clamp(IdleThresholdSeconds, 60, 1800),
        BatchIntervalSeconds = Math.Clamp(BatchIntervalSeconds, 30, 300),
        BatchSize = Math.Clamp(BatchSize, 1, 5000),
        ScreenshotIntervalSeconds = Math.Clamp(ScreenshotIntervalSeconds, 60, 3600),
        ScreenshotMaxLongSide = Math.Clamp(ScreenshotMaxLongSide, 640, 3840),
        ScreenshotQuality = Math.Clamp(ScreenshotQuality, 30, 95),
        ScreenshotMultiMonitorMode = ScreenshotMultiMonitorMode is "merge" or "separate" ? ScreenshotMultiMonitorMode : "merge",
        ScheduleGraceMinutes = Math.Clamp(ScheduleGraceMinutes, 0, 240),
        VideoTriggerMinutes = Math.Clamp(VideoTriggerMinutes, 1, 240),
        VideoOnDemandTimeoutMinutes = Math.Clamp(VideoOnDemandTimeoutMinutes, 1, 480),
        VideoRecordingMode = VideoRecordingMode is "off" or "on_demand" or "always_on" or "scheduled" or "trigger" ? VideoRecordingMode : "on_demand",
        VideoProfile = VideoProfile is "low" or "medium" or "high" ? VideoProfile : "medium",
        VideoScheduleWindows = VideoScheduleWindows ?? [],
        HolidayDates = HolidayDates ?? [],
        PrivateAppPatterns = PrivateAppPatterns ?? [],
    };

    public bool IsWithinCollectionWindow(DateTimeOffset instant)
    {
        if (WorkSchedule is null) return true;
        TimeZoneInfo zone;
        try { zone = TimeZoneInfo.FindSystemTimeZoneById(EmployeeTimezone); }
        catch (TimeZoneNotFoundException) { zone = TimeZoneInfo.Local; }
        catch (InvalidTimeZoneException) { zone = TimeZoneInfo.Local; }
        var local = TimeZoneInfo.ConvertTime(instant, zone);
        if ((HolidayDates ?? []).Contains(local.ToString("yyyy-MM-dd"))) return false;
        var isoDay = local.DayOfWeek == DayOfWeek.Sunday ? 7 : (int)local.DayOfWeek;
        if (!WorkSchedule.Weekdays.Contains(isoDay)) return false;
        if (!TimeSpan.TryParse(WorkSchedule.Start, out var start) || !TimeSpan.TryParse(WorkSchedule.End, out var end))
            return true;
        start -= TimeSpan.FromMinutes(ScheduleGraceMinutes);
        end += TimeSpan.FromMinutes(ScheduleGraceMinutes);
        var current = local.TimeOfDay;
        return end >= start ? current >= start && current <= end : current >= start || current <= end;
    }

    public static AgentRuntimeConfig LoadFromDisk()
    {
        try
        {
            if (!File.Exists(ConfigPath)) return new AgentRuntimeConfig();
            var value = JsonSerializer.Deserialize<AgentRuntimeConfig>(File.ReadAllText(ConfigPath));
            return (value ?? new AgentRuntimeConfig()).Validated();
        }
        catch (Exception)
        {
            return new AgentRuntimeConfig();
        }
    }
}
