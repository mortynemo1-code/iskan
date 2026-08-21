using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Globalization;
using Microsoft.Extensions.Options;
using Microsoft.Win32;
using Workforce.Agent.Shared;
using System.IO.Compression;

namespace Workforce.Agent;

public sealed class ServerClient
{
    private readonly HttpClient _http;
    private readonly AgentOptions _options;

    public ServerClient(HttpClient http, IOptions<AgentOptions> options)
    {
        _http = http;
        _options = options.Value;
        _http.BaseAddress = new Uri(_options.ServerUrl.TrimEnd('/') + "/");
        _http.Timeout = TimeSpan.FromSeconds(20);
    }

    public async Task<RegisterResponse> RegisterAsync(CancellationToken cancellationToken)
    {
        var request = new RegisterRequest(
            _options.InstallationToken,
            Environment.MachineName,
            ReadMachineGuid(),
            Environment.OSVersion.VersionString,
            _options.AgentVersion);
        var response = await _http.PostAsJsonAsync("api/v1/agent/register", request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<RegisterResponse>(cancellationToken))!;
    }

    public async Task<HeartbeatResponse> SendHeartbeatAsync(
        DeviceCredentials credentials,
        string? activityState,
        double cpuPercent,
        long ramMb,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "api/v1/agent/heartbeat");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        request.Content = JsonContent.Create(new HeartbeatRequest(_options.AgentVersion, activityState, cpuPercent, ramMb));
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<HeartbeatResponse>(cancellationToken))!;
    }

    public async Task<IReadOnlyList<AgentCommand>> GetCommandsAsync(
        DeviceCredentials credentials,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "api/v1/agent/commands");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<List<AgentCommand>>(cancellationToken)) ?? [];
    }

    public async Task AcknowledgeCommandAsync(
        DeviceCredentials credentials,
        Guid commandId,
        bool success,
        string? message,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, $"api/v1/agent/commands/{commandId}/ack");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        request.Content = JsonContent.Create(new { success, message });
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
    }

    public async Task<ActivityBatchResponse> SendActivityBatchAsync(
        DeviceCredentials credentials,
        IReadOnlyList<LocalActivityEvent> events,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "api/v1/agent/activity/batch");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        request.Content = JsonContent.Create(new ActivityBatchRequest(DateTimeOffset.UtcNow, events));
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<ActivityBatchResponse>(cancellationToken))!;
    }

    public async Task<(AgentRuntimeConfig? Config, string? ETag)> GetAgentConfigAsync(
        DeviceCredentials credentials,
        string? etag,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "api/v1/agent/config");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        if (!string.IsNullOrWhiteSpace(etag))
            request.Headers.TryAddWithoutValidation("If-None-Match", etag);
        using var response = await _http.SendAsync(request, cancellationToken);
        if (response.StatusCode == System.Net.HttpStatusCode.NotModified)
            return (null, etag);
        response.EnsureSuccessStatusCode();
        var config = await response.Content.ReadFromJsonAsync<AgentRuntimeConfig>(cancellationToken);
        return (config, response.Headers.ETag?.ToString());
    }

    public async Task SendSystemEventAsync(
        DeviceCredentials credentials,
        string code,
        int? windowsSessionId,
        IReadOnlyDictionary<string, object?> details,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "api/v1/agent/events");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        request.Content = JsonContent.Create(new AgentSystemEventRequest(
            code,
            DateTimeOffset.UtcNow,
            windowsSessionId,
            details));
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
    }

    public async Task SendScreenshotAsync(
        DeviceCredentials credentials,
        PendingScreenshot screenshot,
        CancellationToken cancellationToken)
    {
        using var content = new MultipartFormDataContent();
        var image = new ByteArrayContent(await File.ReadAllBytesAsync(screenshot.ImagePath, cancellationToken));
        image.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        content.Add(image, "image", "capture.jpg");
        var thumbnail = new ByteArrayContent(await File.ReadAllBytesAsync(screenshot.ThumbnailPath, cancellationToken));
        thumbnail.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        content.Add(thumbnail, "thumbnail", "thumbnail.jpg");
        content.Add(new StringContent(screenshot.TakenAt.ToString("O")), "taken_at");
        content.Add(new StringContent(screenshot.Width.ToString(CultureInfo.InvariantCulture)), "width");
        content.Add(new StringContent(screenshot.Height.ToString(CultureInfo.InvariantCulture)), "height");
        content.Add(new StringContent(screenshot.MonitorIndex.ToString(CultureInfo.InvariantCulture)), "monitor_index");
        content.Add(new StringContent(screenshot.PHash), "phash");
        content.Add(new StringContent(screenshot.State), "state");
        if (!string.IsNullOrWhiteSpace(screenshot.AppName)) content.Add(new StringContent(screenshot.AppName), "app_name");
        if (!string.IsNullOrWhiteSpace(screenshot.UrlDomain)) content.Add(new StringContent(screenshot.UrlDomain), "url_domain");
        content.Add(new StringContent(screenshot.IsBlurred ? "true" : "false"), "is_blurred");
        using var request = new HttpRequestMessage(HttpMethod.Post, "api/v1/agent/screenshots");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        request.Content = content;
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
    }

    public async Task SendDiagnosticLogsAsync(
        DeviceCredentials credentials,
        string reason,
        CancellationToken cancellationToken)
    {
        var logRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "WorkforceMonitoring", "logs");
        using var archiveBytes = new MemoryStream();
        using (var archive = new ZipArchive(archiveBytes, ZipArchiveMode.Create, true))
        {
            if (Directory.Exists(logRoot))
            {
                foreach (var path in Directory.EnumerateFiles(logRoot, "*.log*").OrderByDescending(File.GetLastWriteTimeUtc))
                {
                    if (archiveBytes.Length >= 18L * 1024 * 1024) break;
                    var entry = archive.CreateEntry(Path.GetFileName(path), CompressionLevel.Fastest);
                    await using var destination = entry.Open();
                    await using var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                    await source.CopyToAsync(destination, cancellationToken);
                }
            }
        }
        archiveBytes.Position = 0;
        using var form = new MultipartFormDataContent();
        var content = new StreamContent(archiveBytes);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/zip");
        form.Add(content, "archive", "agent-diagnostics.zip");
        form.Add(new StringContent(reason), "reason");
        using var request = new HttpRequestMessage(HttpMethod.Post, "api/v1/agent/logs");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        request.Content = form;
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
    }

    public async Task<UpdateManifest> GetUpdateManifestAsync(DeviceCredentials credentials, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "api/v1/agent/update");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        using var response = await _http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<UpdateManifest>(cancellationToken)) ?? new UpdateManifest(false);
    }

    public async Task DownloadUpdateAsync(DeviceCredentials credentials, string relativeUrl, string destination, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, relativeUrl);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credentials.Token);
        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();
        await using var source = await response.Content.ReadAsStreamAsync(cancellationToken);
        await using var target = new FileStream(destination, FileMode.Create, FileAccess.Write, FileShare.None);
        await source.CopyToAsync(target, cancellationToken);
    }

    private static string ReadMachineGuid()
    {
        using var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography");
        return key?.GetValue("MachineGuid")?.ToString()
            ?? throw new InvalidOperationException("Windows MachineGuid is unavailable");
    }
}
