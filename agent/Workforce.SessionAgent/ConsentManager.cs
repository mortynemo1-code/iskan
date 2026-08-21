using System.Text.Json;
using System.Diagnostics;
using Workforce.Agent.Shared;

namespace Workforce.SessionAgent;

public sealed class ConsentManager
{
    private static string ConsentPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "WorkforceMonitoring", "consent.json");

    public async Task EnsureAcceptedAsync(PipeEventSink sink, AgentRuntimeConfig config, CancellationToken cancellationToken)
    {
        if (File.Exists(ConsentPath)) return;
        var result = MessageBox.Show(
            "Работодатель использует систему Workforce Monitoring для учёта рабочего времени.\n\n" +
            "Собираются: активное приложение, заголовок окна, домен и путь сайта без query-параметров, " +
            "периоды активности/простоя/блокировки, а при включении администратором — снимки и трансляция рабочего экрана.\n\n" +
            "Не собираются: нажатия клавиш, введённый текст, микрофон и веб-камера. " +
            "Во время «Личного времени», блокировки и вне рабочего графика снимки и видео отключены.\n\n" +
            $"Хранение: {config.PrivacyRetentionNotice}\nОтветственный: {config.PrivacyContact}\n\n" +
            "Нажмите «ОК», чтобы подтвердить ознакомление.",
            "Уведомление о контроле рабочего времени",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information);
        if (result != DialogResult.OK) throw new OperationCanceledException("Consent was not accepted");
        var acceptedAt = DateTimeOffset.UtcNow;
        Directory.CreateDirectory(Path.GetDirectoryName(ConsentPath)!);
        await File.WriteAllTextAsync(ConsentPath, JsonSerializer.Serialize(new { accepted_at = acceptedAt }), cancellationToken);
        await sink.EnqueueSystemEventAsync(new LocalSystemEvent(
            "consent_accepted", acceptedAt, Process.GetCurrentProcess().SessionId,
            new Dictionary<string, object?> { ["agent_version"] = Application.ProductVersion }), cancellationToken);
    }
}
