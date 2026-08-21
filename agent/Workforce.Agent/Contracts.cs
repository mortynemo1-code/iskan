using System.Text.Json.Serialization;
using System.Text.Json;

namespace Workforce.Agent;

public sealed record RegisterRequest(
    [property: JsonPropertyName("installation_token")] string InstallationToken,
    [property: JsonPropertyName("hostname")] string Hostname,
    [property: JsonPropertyName("machine_guid")] string MachineGuid,
    [property: JsonPropertyName("os_version")] string OsVersion,
    [property: JsonPropertyName("agent_version")] string AgentVersion);

public sealed record RegisterResponse(
    [property: JsonPropertyName("device_id")] Guid DeviceId,
    [property: JsonPropertyName("device_token")] string DeviceToken,
    [property: JsonPropertyName("heartbeat_interval_seconds")] int HeartbeatIntervalSeconds,
    [property: JsonPropertyName("approval_required")] bool ApprovalRequired);

public sealed record HeartbeatRequest(
    [property: JsonPropertyName("agent_version")] string AgentVersion,
    [property: JsonPropertyName("activity_state")] string? ActivityState,
    [property: JsonPropertyName("cpu_percent")] double CpuPercent,
    [property: JsonPropertyName("ram_mb")] long RamMb);

public sealed record AgentCommand(
    [property: JsonPropertyName("id")] Guid Id,
    [property: JsonPropertyName("command")] string Command,
    [property: JsonPropertyName("payload")] JsonElement Payload);

public sealed record HeartbeatResponse(
    [property: JsonPropertyName("server_time")] DateTimeOffset ServerTime,
    [property: JsonPropertyName("next_heartbeat_seconds")] int NextHeartbeatSeconds,
    [property: JsonPropertyName("commands")] IReadOnlyList<AgentCommand> Commands);

public sealed record DeviceCredentials(Guid DeviceId, string Token);

public sealed record AgentSystemEventRequest(
    [property: JsonPropertyName("code")] string Code,
    [property: JsonPropertyName("occurred_at")] DateTimeOffset OccurredAt,
    [property: JsonPropertyName("windows_session_id")] int? WindowsSessionId,
    [property: JsonPropertyName("details")] IReadOnlyDictionary<string, object?> Details);

public sealed record UpdateManifest(
    [property: JsonPropertyName("available")] bool Available,
    [property: JsonPropertyName("rollout_pending")] bool RolloutPending = false,
    [property: JsonPropertyName("id")] Guid? Id = null,
    [property: JsonPropertyName("version")] string? Version = null,
    [property: JsonPropertyName("sha256")] string? Sha256 = null,
    [property: JsonPropertyName("package_url")] string? PackageUrl = null,
    [property: JsonPropertyName("maintenance_start_hour")] int MaintenanceStartHour = 1,
    [property: JsonPropertyName("maintenance_end_hour")] int MaintenanceEndHour = 5);
