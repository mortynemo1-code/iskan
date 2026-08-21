using System.Diagnostics;
using System.Text.Json;
using Workforce.Agent.Shared;

namespace Workforce.SessionAgent;

internal sealed record SessionCommand(Guid Id, string Command, JsonElement Payload);

public sealed class StreamController : IDisposable
{
    private Process? _process;
    private readonly HashSet<Guid> _processed = [];
    private bool _forcedLowProfile;
    private JsonElement? _lastPayload;

    public bool IsStreaming => _process is { HasExited: false };
    public event Action<bool>? StreamingChanged;
    public event Action? ScreenshotRequested;

    public async Task PollAsync(bool allowStart, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(LocalAgentProtocol.CommandDirectory);
        foreach (var path in Directory.EnumerateFiles(LocalAgentProtocol.CommandDirectory, "*.json").OrderBy(path => path))
        {
            cancellationToken.ThrowIfCancellationRequested();
            SessionCommand? command;
            try
            {
                command = JsonSerializer.Deserialize<SessionCommand>(
                    await File.ReadAllTextAsync(path, cancellationToken),
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            }
            catch (JsonException)
            {
                TryDelete(path);
                continue;
            }
            if (command is null || !_processed.Add(command.Id))
            {
                TryDelete(path);
                continue;
            }
            if (command.Command == "start_stream" && allowStart) await StartAsync(command.Payload, cancellationToken);
            if (command.Command == "stop_stream") Stop();
            if (command.Command == "take_screenshot" && allowStart) ScreenshotRequested?.Invoke();
            if (command.Command == "resource_throttle")
            {
                _forcedLowProfile = true;
                if (allowStart && IsStreaming && _lastPayload is { } payload) await StartAsync(payload, cancellationToken);
            }
            TryDelete(path);
        }
    }

    private async Task StartAsync(JsonElement payload, CancellationToken cancellationToken)
    {
        Stop();
        _lastPayload = payload.Clone();
        var whipUrl = payload.GetProperty("publish_url").GetString()
            ?? throw new InvalidOperationException("WHIP URL is missing");
        var rtspUrl = payload.TryGetProperty("rtsp_url", out var rtsp) ? rtsp.GetString() : null;
        var profile = _forcedLowProfile ? "low" : payload.TryGetProperty("profile", out var profileValue) ? profileValue.GetString() : "medium";
        var (width, fps, bitrate) = profile switch
        {
            "low" => (1280, 5, "250k"),
            "high" => (1920, 15, "1200k"),
            _ => (1280, 10, "500k"),
        };
        _process = await StartWithEncoderFallback(whipUrl, width, fps, bitrate, true, cancellationToken);
        if (_process is null && !string.IsNullOrWhiteSpace(rtspUrl))
        {
            _process = await StartWithEncoderFallback(rtspUrl, width, fps, bitrate, false, cancellationToken);
        }
        if (_process is null || _process.HasExited) throw new InvalidOperationException("FFmpeg could not start screen streaming");
        StreamingChanged?.Invoke(true);
    }

    private static async Task<Process?> StartWithEncoderFallback(string url, int width, int fps, string bitrate, bool whip, CancellationToken cancellationToken)
    {
        foreach (var encoder in new[] { "h264_nvenc", "h264_qsv", "h264_amf", "libx264" })
        {
            var process = StartFfmpeg(url, width, fps, bitrate, whip, encoder);
            await Task.Delay(TimeSpan.FromMilliseconds(900), cancellationToken);
            if (!process.HasExited) return process;
            process.Dispose();
        }
        return null;
    }

    private static Process StartFfmpeg(string url, int width, int fps, string bitrate, bool whip, string encoder)
    {
        var packaged = Path.Combine(AppContext.BaseDirectory, "ffmpeg.exe");
        var start = new ProcessStartInfo(File.Exists(packaged) ? packaged : "ffmpeg")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
        };
        foreach (var argument in new[] {
            "-hide_banner", "-loglevel", "warning", "-f", "gdigrab", "-draw_mouse", "1",
            "-framerate", fps.ToString(), "-i", "desktop",
            "-vf", $"scale={width}:-2:force_original_aspect_ratio=decrease",
            "-c:v", encoder,
            "-pix_fmt", "yuv420p", "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate,
            "-g", (fps * 2).ToString()
        }) start.ArgumentList.Add(argument);
        if (encoder == "libx264")
            foreach (var argument in new[] { "-preset", "ultrafast", "-tune", "zerolatency" }) start.ArgumentList.Add(argument);
        if (whip)
        {
            foreach (var argument in new[] { "-an", "-f", "whip", url }) start.ArgumentList.Add(argument);
        }
        else
        {
            foreach (var argument in new[] { "-an", "-f", "rtsp", "-rtsp_transport", "tcp", url })
                start.ArgumentList.Add(argument);
        }
        return Process.Start(start) ?? throw new InvalidOperationException("FFmpeg process was not created");
    }

    public void Stop()
    {
        if (_process is null) return;
        try
        {
            if (!_process.HasExited) _process.Kill(true);
        }
        catch (InvalidOperationException) { }
        _process.Dispose();
        _process = null;
        StreamingChanged?.Invoke(false);
    }

    private static void TryDelete(string path)
    {
        try { File.Delete(path); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    public void Dispose() => Stop();
}
