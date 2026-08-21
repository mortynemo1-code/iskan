using System.Runtime.InteropServices;

namespace Workforce.SessionAgent;

public sealed record InputSnapshot(int Keystrokes, int Clicks, int MouseDistance);

/// <summary>Counts input intensity only. It never inspects or stores key codes or typed content.</summary>
public sealed class InputCounter : IDisposable
{
    private const int WhKeyboardLl = 13;
    private const int WhMouseLl = 14;
    private const int WmKeyDown = 0x0100;
    private const int WmSysKeyDown = 0x0104;
    private const int WmMouseMove = 0x0200;
    private static readonly HashSet<int> ClickMessages = [0x0201, 0x0204, 0x0207, 0x020B, 0x020E];
    private readonly HookProc _keyboardCallback;
    private readonly HookProc _mouseCallback;
    private readonly nint _keyboardHook;
    private readonly nint _mouseHook;
    private long _keystrokes;
    private long _clicks;
    private long _mouseDistance;
    private Point _lastPoint;
    private bool _hasPoint;

    public InputCounter()
    {
        _keyboardCallback = KeyboardHook;
        _mouseCallback = MouseHook;
        using var process = System.Diagnostics.Process.GetCurrentProcess();
        using var module = process.MainModule;
        var handle = GetModuleHandle(module?.ModuleName);
        _keyboardHook = SetWindowsHookEx(WhKeyboardLl, _keyboardCallback, handle, 0);
        _mouseHook = SetWindowsHookEx(WhMouseLl, _mouseCallback, handle, 0);
    }

    public InputSnapshot SnapshotAndReset() => new(
        Clamp(Interlocked.Exchange(ref _keystrokes, 0)),
        Clamp(Interlocked.Exchange(ref _clicks, 0)),
        Clamp(Interlocked.Exchange(ref _mouseDistance, 0)));

    private nint KeyboardHook(int code, nint message, nint data)
    {
        if (code >= 0 && ((int)message == WmKeyDown || (int)message == WmSysKeyDown)) Interlocked.Increment(ref _keystrokes);
        return CallNextHookEx(_keyboardHook, code, message, data);
    }

    private nint MouseHook(int code, nint message, nint data)
    {
        if (code >= 0)
        {
            var kind = (int)message;
            if (ClickMessages.Contains(kind)) Interlocked.Increment(ref _clicks);
            if (kind == WmMouseMove)
            {
                var value = Marshal.PtrToStructure<MouseHookData>(data).Point;
                if (_hasPoint)
                {
                    var dx = (long)value.X - _lastPoint.X;
                    var dy = (long)value.Y - _lastPoint.Y;
                    Interlocked.Add(ref _mouseDistance, (long)Math.Sqrt(dx * dx + dy * dy));
                }
                _lastPoint = value;
                _hasPoint = true;
            }
        }
        return CallNextHookEx(_mouseHook, code, message, data);
    }

    private static int Clamp(long value) => (int)Math.Min(int.MaxValue, Math.Max(0, value));

    public void Dispose()
    {
        if (_keyboardHook != 0) UnhookWindowsHookEx(_keyboardHook);
        if (_mouseHook != 0) UnhookWindowsHookEx(_mouseHook);
    }

    private delegate nint HookProc(int code, nint message, nint data);
    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X; public int Y; }
    [StructLayout(LayoutKind.Sequential)] private struct MouseHookData { public Point Point; public uint MouseData; public uint Flags; public uint Time; public nuint ExtraInfo; }
    [DllImport("user32.dll", SetLastError = true)] private static extern nint SetWindowsHookEx(int hook, HookProc callback, nint module, uint threadId);
    [DllImport("user32.dll")] private static extern bool UnhookWindowsHookEx(nint hook);
    [DllImport("user32.dll")] private static extern nint CallNextHookEx(nint hook, int code, nint message, nint data);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern nint GetModuleHandle(string? moduleName);
}
