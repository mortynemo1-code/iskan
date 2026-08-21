using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Microsoft.Extensions.Options;

namespace Workforce.Agent;

public sealed class UpdateWorker : BackgroundService
{
    private readonly DeviceIdentityProvider _identity;
    private readonly ServerClient _server;
    private readonly AgentOptions _options;
    private readonly ILogger<UpdateWorker> _logger;
    private readonly UpdateSignal _signal;

    public UpdateWorker(DeviceIdentityProvider identity, ServerClient server, IOptions<AgentOptions> options, UpdateSignal signal, ILogger<UpdateWorker> logger) =>
        (_identity, _server, _options, _signal, _logger) = (identity, server, options.Value, signal, logger);

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var credentials = await _identity.GetAsync(stoppingToken);
                var manifest = await _server.GetUpdateManifestAsync(credentials, stoppingToken);
                if (ShouldInstall(manifest))
                    await InstallAsync(credentials, manifest, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
            catch (Exception exception) { _logger.LogWarning(exception, "Agent update check failed"); }
            await _signal.WaitAsync(TimeSpan.FromHours(1), stoppingToken);
        }
    }

    private bool ShouldInstall(UpdateManifest manifest)
    {
        if (!manifest.Available || string.IsNullOrWhiteSpace(manifest.Version) || string.IsNullOrWhiteSpace(manifest.PackageUrl)) return false;
        if (!Version.TryParse(manifest.Version.Split('-', '+')[0], out var offered) || !Version.TryParse(_options.AgentVersion.Split('-', '+')[0], out var current)) return false;
        var hour = DateTime.Now.Hour;
        var insideWindow = manifest.MaintenanceEndHour >= manifest.MaintenanceStartHour
            ? hour >= manifest.MaintenanceStartHour && hour < manifest.MaintenanceEndHour
            : hour >= manifest.MaintenanceStartHour || hour < manifest.MaintenanceEndHour;
        return offered > current && insideWindow;
    }

    private async Task InstallAsync(DeviceCredentials credentials, UpdateManifest manifest, CancellationToken cancellationToken)
    {
        var package = Path.Combine(Path.GetTempPath(), $"workforce-agent-{manifest.Version}.msi");
        await _server.DownloadUpdateAsync(credentials, manifest.PackageUrl!, package, cancellationToken);
        await using (var stream = File.OpenRead(package))
        {
            var checksum = Convert.ToHexString(await SHA256.HashDataAsync(stream, cancellationToken)).ToLowerInvariant();
            if (!string.Equals(checksum, manifest.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Update checksum mismatch");
        }
        if (!AuthenticodeVerifier.IsTrusted(package)) throw new InvalidDataException("Update signature is not trusted");
        var start = new ProcessStartInfo("msiexec.exe") { UseShellExecute = false, CreateNoWindow = true };
        foreach (var argument in new[] { "/i", package, "/qn", "/norestart", $"SERVER={_options.ServerUrl}", $"TOKEN={_options.InstallationToken}" })
            start.ArgumentList.Add(argument);
        _logger.LogInformation("Installing signed agent update {Version}", manifest.Version);
        Process.Start(start);
    }
}

internal static class AuthenticodeVerifier
{
    private static readonly Guid ActionGenericVerifyV2 = new("00AAC56B-CD44-11D0-8CC2-00C04FC295EE");

    public static bool IsTrusted(string filePath)
    {
        using var fileInfo = new WinTrustFileInfo(filePath);
        using var data = new WinTrustData(fileInfo);
        var action = ActionGenericVerifyV2;
        return WinVerifyTrust(IntPtr.Zero, ref action, data) == 0;
    }

    [DllImport("wintrust.dll", ExactSpelling = true, SetLastError = true)]
    private static extern int WinVerifyTrust(IntPtr window, ref Guid action, WinTrustData data);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private sealed class WinTrustFileInfo : IDisposable
    {
        public uint StructSize = (uint)Marshal.SizeOf<WinTrustFileInfo>();
        public IntPtr FilePath;
        public IntPtr FileHandle = IntPtr.Zero;
        public IntPtr KnownSubject = IntPtr.Zero;
        public WinTrustFileInfo(string path) => FilePath = Marshal.StringToCoTaskMemUni(path);
        public void Dispose() => Marshal.FreeCoTaskMem(FilePath);
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private sealed class WinTrustData : IDisposable
    {
        public uint StructSize = (uint)Marshal.SizeOf<WinTrustData>();
        public IntPtr PolicyCallbackData = IntPtr.Zero;
        public IntPtr SIPClientData = IntPtr.Zero;
        public uint UIChoice = 2;
        public uint RevocationChecks = 1;
        public uint UnionChoice = 1;
        public IntPtr FileInfo;
        public uint StateAction = 0;
        public IntPtr StateData = IntPtr.Zero;
        public string? URLReference = null;
        public uint ProviderFlags = 0x00000080;
        public uint UIContext = 0;
        public WinTrustData(WinTrustFileInfo file)
        {
            FileInfo = Marshal.AllocCoTaskMem(Marshal.SizeOf<WinTrustFileInfo>());
            Marshal.StructureToPtr(file, FileInfo, false);
        }
        public void Dispose()
        {
            Marshal.DestroyStructure<WinTrustFileInfo>(FileInfo);
            Marshal.FreeCoTaskMem(FileInfo);
        }
    }
}
