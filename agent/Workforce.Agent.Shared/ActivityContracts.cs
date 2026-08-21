using System.Text.Json.Serialization;

namespace Workforce.Agent.Shared;

public static class LocalAgentProtocol
{
    public const string PipeName = "WorkforceMonitoring.Activity.v1";
    public static string CommandDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonDocuments),
        "WorkforceMonitoring",
        "commands");
}

public static class ActivityStates
{
    public const string Productive = "PRODUCTIVE";
    public const string Neutral = "NEUTRAL";
    public const string Unproductive = "UNPRODUCTIVE";
    public const string Idle = "IDLE";
    public const string Locked = "LOCKED";
    public const string Break = "BREAK";
}

public static class LocalMessageKinds
{
    public const string Status = "status";
    public const string ActivityEvent = "activity_event";
    public const string Screenshot = "screenshot";
    public const string SystemEvent = "system_event";
}

public sealed record ActivitySample(
    DateTimeOffset CapturedAt,
    string State,
    string? ProcessName,
    string? AppName,
    string? WindowTitle,
    string? UrlDomain,
    string? UrlPath,
    int WindowsSessionId,
    bool IsRemote,
    TimeSpan IdleDuration,
    string? WindowsSid = null,
    string? WindowsUsername = null,
    int Keystrokes = 0,
    int Clicks = 0,
    int MouseDistance = 0);

public sealed record LocalActivityEvent(
    [property: JsonPropertyName("event_uuid")] Guid EventUuid,
    [property: JsonPropertyName("ts_start")] DateTimeOffset StartedAt,
    [property: JsonPropertyName("ts_end")] DateTimeOffset EndedAt,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("process_name")] string? ProcessName,
    [property: JsonPropertyName("app_name")] string? AppName,
    [property: JsonPropertyName("window_title")] string? WindowTitle,
    [property: JsonPropertyName("url_domain")] string? UrlDomain,
    [property: JsonPropertyName("url_path")] string? UrlPath,
    [property: JsonPropertyName("windows_session_id")] int WindowsSessionId,
    [property: JsonPropertyName("is_remote")] bool IsRemote,
    [property: JsonPropertyName("keystrokes")] int Keystrokes,
    [property: JsonPropertyName("clicks")] int Clicks,
    [property: JsonPropertyName("mouse_distance")] int MouseDistance,
    [property: JsonPropertyName("windows_sid")] string? WindowsSid = null,
    [property: JsonPropertyName("windows_username")] string? WindowsUsername = null);

public sealed record LocalScreenshot(
    [property: JsonPropertyName("taken_at")] DateTimeOffset TakenAt,
    [property: JsonPropertyName("width")] int Width,
    [property: JsonPropertyName("height")] int Height,
    [property: JsonPropertyName("monitor_index")] int MonitorIndex,
    [property: JsonPropertyName("phash")] string PHash,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("app_name")] string? AppName,
    [property: JsonPropertyName("url_domain")] string? UrlDomain,
    [property: JsonPropertyName("image_base64")] string ImageBase64,
    [property: JsonPropertyName("thumbnail_base64")] string ThumbnailBase64,
    [property: JsonPropertyName("is_blurred")] bool IsBlurred = false);

public sealed record LocalSystemEvent(
    [property: JsonPropertyName("code")] string Code,
    [property: JsonPropertyName("occurred_at")] DateTimeOffset OccurredAt,
    [property: JsonPropertyName("windows_session_id")] int? WindowsSessionId,
    [property: JsonPropertyName("details")] IReadOnlyDictionary<string, object?> Details);

public sealed record LocalAgentMessage(
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("state")] string? State,
    [property: JsonPropertyName("event")] LocalActivityEvent? Event,
    [property: JsonPropertyName("screenshot")] LocalScreenshot? Screenshot,
    [property: JsonPropertyName("system_event")] LocalSystemEvent? SystemEvent)
{
    public static LocalAgentMessage ForStatus(string state) => new(LocalMessageKinds.Status, state, null, null, null);
    public static LocalAgentMessage ForEvent(LocalActivityEvent activityEvent) =>
        new(LocalMessageKinds.ActivityEvent, activityEvent.State, activityEvent, null, null);
    public static LocalAgentMessage ForScreenshot(LocalScreenshot screenshot) =>
        new(LocalMessageKinds.Screenshot, screenshot.State, null, screenshot, null);
    public static LocalAgentMessage ForSystemEvent(LocalSystemEvent systemEvent) =>
        new(LocalMessageKinds.SystemEvent, null, null, null, systemEvent);
}

public sealed record ActivityBatchRequest(
    [property: JsonPropertyName("sent_at")] DateTimeOffset SentAt,
    [property: JsonPropertyName("events")] IReadOnlyList<LocalActivityEvent> Events);

public sealed record ActivityBatchResponse(
    [property: JsonPropertyName("accepted")] int Accepted,
    [property: JsonPropertyName("duplicates")] int Duplicates);
