using System.Text.Json;
using Workforce.Agent.Shared;

namespace Workforce.Agent;

public sealed record PendingScreenshot(
    string Id,
    DateTimeOffset TakenAt,
    int Width,
    int Height,
    int MonitorIndex,
    string PHash,
    string State,
    string? AppName,
    string? UrlDomain,
    bool IsBlurred,
    string ImagePath,
    string ThumbnailPath,
    string MetadataPath);

internal sealed record ScreenshotMetadata(
    string Id,
    DateTimeOffset TakenAt,
    int Width,
    int Height,
    int MonitorIndex,
    string PHash,
    string State,
    string? AppName,
    string? UrlDomain,
    bool IsBlurred);

public sealed class ScreenshotQueue
{
    private const long MaxBytes = 1024L * 1024 * 1024;
    private readonly string _root = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
        "WorkforceMonitoring",
        "screenshots-queue");
    private readonly SemaphoreSlim _gate = new(1, 1);

    public Task InitializeAsync(CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(_root);
        return Task.CompletedTask;
    }

    public async Task EnqueueAsync(LocalScreenshot screenshot, CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            Directory.CreateDirectory(_root);
            var id = $"{screenshot.TakenAt.UtcDateTime:yyyyMMddHHmmssfff}-{Guid.NewGuid():N}";
            var imagePath = Path.Combine(_root, id + ".jpg");
            var thumbPath = Path.Combine(_root, id + ".thumb.jpg");
            var metadataPath = Path.Combine(_root, id + ".json");
            await File.WriteAllBytesAsync(imagePath, Convert.FromBase64String(screenshot.ImageBase64), cancellationToken);
            await File.WriteAllBytesAsync(thumbPath, Convert.FromBase64String(screenshot.ThumbnailBase64), cancellationToken);
            var metadata = new ScreenshotMetadata(
                id, screenshot.TakenAt, screenshot.Width, screenshot.Height, screenshot.MonitorIndex,
                screenshot.PHash, screenshot.State, screenshot.AppName, screenshot.UrlDomain, screenshot.IsBlurred);
            await File.WriteAllTextAsync(metadataPath, JsonSerializer.Serialize(metadata), cancellationToken);
            await TrimAsync(cancellationToken);
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task<PendingScreenshot?> TakeAsync(CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            foreach (var metadataPath in Directory.EnumerateFiles(_root, "*.json").OrderBy(path => path))
            {
                try
                {
                    var metadata = JsonSerializer.Deserialize<ScreenshotMetadata>(
                        await File.ReadAllTextAsync(metadataPath, cancellationToken));
                    if (metadata is null) continue;
                    var imagePath = Path.Combine(_root, metadata.Id + ".jpg");
                    var thumbPath = Path.Combine(_root, metadata.Id + ".thumb.jpg");
                    if (!File.Exists(imagePath) || !File.Exists(thumbPath))
                    {
                        DeleteFiles(metadata.Id);
                        continue;
                    }
                    return new PendingScreenshot(
                        metadata.Id, metadata.TakenAt, metadata.Width, metadata.Height,
                        metadata.MonitorIndex, metadata.PHash, metadata.State, metadata.AppName,
                        metadata.UrlDomain, metadata.IsBlurred, imagePath, thumbPath, metadataPath);
                }
                catch (JsonException)
                {
                    File.Delete(metadataPath);
                }
            }
            return null;
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task DeleteAsync(PendingScreenshot screenshot, CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try { DeleteFiles(screenshot.Id); }
        finally { _gate.Release(); }
    }

    private async Task TrimAsync(CancellationToken cancellationToken)
    {
        var files = Directory.EnumerateFiles(_root).Select(path => new FileInfo(path)).ToList();
        var total = files.Sum(file => file.Length);
        if (total <= MaxBytes) return;
        foreach (var metadata in files.Where(file => file.Extension == ".json").OrderBy(file => file.Name))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var id = Path.GetFileNameWithoutExtension(metadata.Name);
            var reclaimed = new[] { metadata.FullName, Path.Combine(_root, id + ".jpg"), Path.Combine(_root, id + ".thumb.jpg") }
                .Where(File.Exists).Sum(path => new FileInfo(path).Length);
            DeleteFiles(id);
            total -= reclaimed;
            if (total <= MaxBytes) break;
            await Task.Yield();
        }
    }

    private void DeleteFiles(string id)
    {
        foreach (var suffix in new[] { ".json", ".jpg", ".thumb.jpg" })
        {
            var path = Path.Combine(_root, id + suffix);
            if (File.Exists(path)) File.Delete(path);
        }
    }
}
