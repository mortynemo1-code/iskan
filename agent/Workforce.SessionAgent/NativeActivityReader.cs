using System.Diagnostics;
using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Text;
using System.Security.Principal;
using Workforce.Agent.Shared;

namespace Workforce.SessionAgent;

public sealed class NativeActivityReader
{
    private int _idleThresholdSeconds;
    private volatile bool _collectWindowTitles = true;
    private volatile bool _collectBrowserUrls = true;
    private readonly ConcurrentDictionary<uint, (string ProcessName, string AppName)> _processCache = new();
    private readonly BrowserUrlReader _browserUrlReader = new();
    private readonly MediaPlaybackDetector _mediaPlaybackDetector = new();
    private volatile bool _treatMediaPlaybackAsActivity = true;
    private volatile bool _isLocked;
    private volatile bool _isBreak;
    private readonly string? _windowsSid;
    private readonly string? _windowsUsername;

    public NativeActivityReader(int idleThresholdSeconds = 300)
    {
        _idleThresholdSeconds = idleThresholdSeconds;
        using var identity = WindowsIdentity.GetCurrent();
        _windowsSid = identity.User?.Value;
        _windowsUsername = identity.Name;
        Microsoft.Win32.SystemEvents.SessionSwitch += (_, args) =>
        {
            if (args.Reason == Microsoft.Win32.SessionSwitchReason.SessionLock) _isLocked = true;
            if (args.Reason == Microsoft.Win32.SessionSwitchReason.SessionUnlock) _isLocked = false;
        };
    }

    public bool IsBreak
    {
        get => _isBreak;
        set => _isBreak = value;
    }

    public void ApplyConfig(AgentRuntimeConfig config)
    {
        Volatile.Write(ref _idleThresholdSeconds, config.IdleThresholdSeconds);
        _collectWindowTitles = config.CollectWindowTitles;
        _collectBrowserUrls = config.CollectBrowserUrls;
        _treatMediaPlaybackAsActivity = config.TreatMediaPlaybackAsActivity;
    }

    public ActivitySample Capture()
    {
        var now = DateTimeOffset.UtcNow;
        var idle = GetIdleDuration();
        var sessionId = Process.GetCurrentProcess().SessionId;
        var isRemote = SystemInformation.TerminalServerSession;

        if (_isBreak)
            return new ActivitySample(
                now, ActivityStates.Break, null, null, null, null, null, sessionId, isRemote, idle);
        if (_isLocked)
            return new ActivitySample(
                now, ActivityStates.Locked, null, null, null, null, null, sessionId, isRemote, idle);

        var window = GetForegroundWindow();
        var title = _collectWindowTitles ? ReadWindowTitle(window) : null;
        GetWindowThreadProcessId(window, out var processId);
        var processInfo = ReadProcess(processId);
        var browserLocation = _collectBrowserUrls
            ? _browserUrlReader.Read(window, processInfo.ProcessName)
            : null;

        var mediaIsPlaying = _treatMediaPlaybackAsActivity &&
            idle.TotalSeconds >= Volatile.Read(ref _idleThresholdSeconds) &&
            _mediaPlaybackDetector.IsProcessRenderingAudio(processId);
        var state = idle.TotalSeconds >= Volatile.Read(ref _idleThresholdSeconds) && !mediaIsPlaying
            ? ActivityStates.Idle
            : ActivityStates.Neutral;
        return new ActivitySample(
            now,
            state,
            processInfo.ProcessName,
            processInfo.AppName,
            title,
            browserLocation?.Domain,
            browserLocation?.Path,
            sessionId,
            isRemote,
            idle,
            _windowsSid,
            _windowsUsername);
    }

    private (string? ProcessName, string? AppName) ReadProcess(uint processId)
    {
        if (processId == 0) return (null, null);
        try
        {
            return _processCache.GetOrAdd(processId, id =>
            {
                using var process = Process.GetProcessById(unchecked((int)id));
                var processName = process.ProcessName + ".exe";
                var appName = process.MainModule?.FileVersionInfo.FileDescription ?? process.ProcessName;
                return (processName, appName);
            });
        }
        catch (Exception)
        {
            return ($"pid-{processId}", $"Process {processId}");
        }
    }

    private static string? ReadWindowTitle(nint window)
    {
        var length = GetWindowTextLength(window);
        if (length <= 0) return null;
        var buffer = new StringBuilder(Math.Min(length + 1, 1025));
        GetWindowText(window, buffer, buffer.Capacity);
        var value = buffer.ToString().Trim();
        return value.Length == 0 ? null : value;
    }

    private static TimeSpan GetIdleDuration()
    {
        var info = new LastInputInfo { Size = (uint)Marshal.SizeOf<LastInputInfo>() };
        if (!GetLastInputInfo(ref info)) return TimeSpan.Zero;
        var elapsed = unchecked((uint)Environment.TickCount - info.Time);
        return TimeSpan.FromMilliseconds(elapsed);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct LastInputInfo
    {
        public uint Size;
        public uint Time;
    }

    [DllImport("user32.dll")]
    private static extern nint GetForegroundWindow();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(nint window, StringBuilder text, int count);

    [DllImport("user32.dll")]
    private static extern int GetWindowTextLength(nint window);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(nint window, out uint processId);

    [DllImport("user32.dll")]
    private static extern bool GetLastInputInfo(ref LastInputInfo info);
}
