using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Extensions.Options;

namespace Workforce.Agent;

public sealed class SessionAgentLauncherWorker : BackgroundService
{
    private const uint CreateUnicodeEnvironment = 0x00000400;
    private readonly AgentOptions _options;
    private readonly ILogger<SessionAgentLauncherWorker> _logger;
    private readonly DeviceIdentityProvider _identity;
    private readonly ServerClient _server;
    private readonly HashSet<int> _knownSessions = [];

    public SessionAgentLauncherWorker(
        IOptions<AgentOptions> options,
        DeviceIdentityProvider identity,
        ServerClient server,
        ILogger<SessionAgentLauncherWorker> logger)
    {
        _options = options.Value;
        _identity = identity;
        _server = server;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            var executable = ResolveExecutablePath();
            if (!File.Exists(executable))
            {
                _logger.LogError("Session Agent executable not found: {Path}", executable);
                await Task.Delay(TimeSpan.FromSeconds(30), stoppingToken);
                continue;
            }

            foreach (var sessionId in EnumerateActiveSessions())
            {
                if (IsRunningInSession(executable, sessionId))
                {
                    _knownSessions.Add(sessionId);
                    continue;
                }
                var unexpectedStop = _knownSessions.Contains(sessionId);
                if (unexpectedStop)
                    _logger.LogWarning("Session Agent stopped unexpectedly in session {SessionId}; restarting", sessionId);
                if (TryLaunch(executable, sessionId))
                {
                    _knownSessions.Add(sessionId);
                    _logger.LogInformation("Session Agent started in session {SessionId}", sessionId);
                    if (unexpectedStop) await ReportTamperAsync(sessionId, stoppingToken);
                }
            }

            await Task.Delay(TimeSpan.FromSeconds(10), stoppingToken);
        }
    }

    private async Task ReportTamperAsync(int sessionId, CancellationToken cancellationToken)
    {
        try
        {
            var credentials = await _identity.GetAsync(cancellationToken);
            await _server.SendSystemEventAsync(
                credentials,
                "agent_tamper",
                sessionId,
                new Dictionary<string, object?> { ["reason"] = "session_agent_stopped" },
                cancellationToken);
        }
        catch (Exception exception) when (!cancellationToken.IsCancellationRequested)
        {
            _logger.LogWarning(exception, "Could not report agent_tamper for session {SessionId}", sessionId);
        }
    }

    private string ResolveExecutablePath() => Path.IsPathRooted(_options.SessionAgentPath)
        ? _options.SessionAgentPath
        : Path.Combine(AppContext.BaseDirectory, _options.SessionAgentPath);

    private static bool IsRunningInSession(string executable, int sessionId)
    {
        var processName = Path.GetFileNameWithoutExtension(executable);
        foreach (var process in Process.GetProcessesByName(processName))
        {
            using (process)
            {
                try
                {
                    if (process.SessionId == sessionId) return true;
                }
                catch (InvalidOperationException) { }
            }
        }
        return false;
    }

    private bool TryLaunch(string executable, int sessionId)
    {
        if (!WTSQueryUserToken((uint)sessionId, out var userToken))
        {
            _logger.LogWarning("WTSQueryUserToken failed for session {SessionId}: {Error}",
                sessionId, Marshal.GetLastWin32Error());
            return false;
        }
        nint environment = 0;
        try
        {
            if (!CreateEnvironmentBlock(out environment, userToken, false))
                environment = 0;
            var startup = new StartupInfo
            {
                Size = Marshal.SizeOf<StartupInfo>(),
                Desktop = @"winsta0\default",
            };
            var commandLine = $"\"{executable}\" --session-id {sessionId}";
            var success = CreateProcessAsUser(
                userToken,
                executable,
                commandLine,
                0,
                0,
                false,
                CreateUnicodeEnvironment,
                environment,
                Path.GetDirectoryName(executable),
                ref startup,
                out var processInfo);
            if (!success)
            {
                _logger.LogWarning("CreateProcessAsUser failed for session {SessionId}: {Error}",
                    sessionId, Marshal.GetLastWin32Error());
                return false;
            }
            CloseHandle(processInfo.Thread);
            CloseHandle(processInfo.Process);
            return true;
        }
        finally
        {
            if (environment != 0) DestroyEnvironmentBlock(environment);
            CloseHandle(userToken);
        }
    }

    private static IReadOnlyList<int> EnumerateActiveSessions()
    {
        var result = new List<int>();
        if (!WTSEnumerateSessions(0, 0, 1, out var buffer, out var count)) return result;
        try
        {
            var size = Marshal.SizeOf<WtsSessionInfo>();
            for (var index = 0; index < count; index++)
            {
                var item = Marshal.PtrToStructure<WtsSessionInfo>(IntPtr.Add(buffer, index * size));
                if (item.State == WtsConnectState.Active) result.Add(item.SessionId);
            }
        }
        finally
        {
            WTSFreeMemory(buffer);
        }
        return result;
    }

    private enum WtsConnectState
    {
        Active,
        Connected,
        ConnectQuery,
        Shadow,
        Disconnected,
        Idle,
        Listen,
        Reset,
        Down,
        Init,
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WtsSessionInfo
    {
        public int SessionId;
        public nint WinStationName;
        public WtsConnectState State;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int Size;
        public string? Reserved;
        public string? Desktop;
        public string? Title;
        public int X;
        public int Y;
        public int XSize;
        public int YSize;
        public int XCountChars;
        public int YCountChars;
        public int FillAttribute;
        public int Flags;
        public short ShowWindow;
        public short Reserved2;
        public nint ReservedPointer;
        public nint StdInput;
        public nint StdOutput;
        public nint StdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation
    {
        public nint Process;
        public nint Thread;
        public int ProcessId;
        public int ThreadId;
    }

    [DllImport("wtsapi32.dll", SetLastError = true)]
    private static extern bool WTSEnumerateSessions(
        nint server, int reserved, int version, out nint sessionInfo, out int count);

    [DllImport("wtsapi32.dll")]
    private static extern void WTSFreeMemory(nint memory);

    [DllImport("wtsapi32.dll", SetLastError = true)]
    private static extern bool WTSQueryUserToken(uint sessionId, out nint token);

    [DllImport("userenv.dll", SetLastError = true)]
    private static extern bool CreateEnvironmentBlock(out nint environment, nint token, bool inherit);

    [DllImport("userenv.dll")]
    private static extern bool DestroyEnvironmentBlock(nint environment);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcessAsUser(
        nint token,
        string? applicationName,
        string commandLine,
        nint processAttributes,
        nint threadAttributes,
        bool inheritHandles,
        uint creationFlags,
        nint environment,
        string? currentDirectory,
        ref StartupInfo startupInfo,
        out ProcessInformation processInformation);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(nint handle);
}
