namespace Workforce.Agent;

public sealed class AgentOptions
{
    public string ServerUrl { get; init; } = "http://localhost:8080";
    public string InstallationToken { get; init; } = "";
    public string AgentVersion { get; init; } = "0.1.0";
    public int HeartbeatIntervalSeconds { get; init; } = 30;
    public int BatchIntervalSeconds { get; init; } = 60;
    public int BatchSize { get; init; } = 500;
    public int ConfigRefreshIntervalSeconds { get; init; } = 300;
    public string SessionAgentPath { get; init; } = "Workforce.SessionAgent.exe";
    public string? ProxyUrl { get; init; }
    public string? ProxyUsername { get; init; }
    public string? ProxyPassword { get; init; }
    public string? ServerCertificateSha256 { get; init; }
}
