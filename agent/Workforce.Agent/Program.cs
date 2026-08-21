using Workforce.Agent;
using Serilog;
using Microsoft.Extensions.Options;
using System.Net;
using System.Security.Cryptography;

var logDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "WorkforceMonitoring", "logs");
Directory.CreateDirectory(logDirectory);
Log.Logger = new LoggerConfiguration()
    .MinimumLevel.Information()
    .WriteTo.File(Path.Combine(logDirectory, "agent-.log"), rollingInterval: RollingInterval.Day,
        retainedFileCountLimit: 7, fileSizeLimitBytes: 50L * 1024 * 1024, rollOnFileSizeLimit: true,
        outputTemplate: "{Timestamp:O} [{Level:u3}] {Message:lj}{NewLine}{Exception}")
    .CreateLogger();
var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddSerilog();
builder.Services.AddWindowsService(options => options.ServiceName = "Workforce Monitoring Agent");
builder.Services.Configure<AgentOptions>(builder.Configuration.GetSection("Agent"));
builder.Services.AddSingleton<DeviceCredentialsStore>();
builder.Services.AddSingleton<DeviceIdentityProvider>();
builder.Services.AddSingleton<ActivityQueue>();
builder.Services.AddSingleton<ScreenshotQueue>();
builder.Services.AddSingleton<CurrentActivityState>();
builder.Services.AddSingleton<AgentConfigurationStore>();
builder.Services.AddSingleton<AgentCommandStore>();
builder.Services.AddSingleton<ResourceUsageSampler>();
builder.Services.AddSingleton<UpdateSignal>();
builder.Services.AddHttpClient<ServerClient>().ConfigurePrimaryHttpMessageHandler(services =>
{
    var options = services.GetRequiredService<IOptions<AgentOptions>>().Value;
    var handler = new HttpClientHandler { UseProxy = true };
    if (!string.IsNullOrWhiteSpace(options.ProxyUrl))
    {
        var proxy = new WebProxy(options.ProxyUrl);
        if (!string.IsNullOrWhiteSpace(options.ProxyUsername))
            proxy.Credentials = new NetworkCredential(options.ProxyUsername, options.ProxyPassword);
        handler.Proxy = proxy;
    }
    if (!string.IsNullOrWhiteSpace(options.ServerCertificateSha256))
    {
        var expected = options.ServerCertificateSha256.Replace(":", "", StringComparison.Ordinal).Trim();
        handler.ServerCertificateCustomValidationCallback = (_, certificate, _, _) =>
            certificate is not null && string.Equals(Convert.ToHexString(SHA256.HashData(certificate.RawData)), expected, StringComparison.OrdinalIgnoreCase);
    }
    return handler;
});
builder.Services.AddHostedService<HeartbeatWorker>();
builder.Services.AddHostedService<PipeReceiverWorker>();
builder.Services.AddHostedService<ActivityUploadWorker>();
builder.Services.AddHostedService<ScreenshotUploadWorker>();
builder.Services.AddHostedService<ConfigurationSyncWorker>();
builder.Services.AddHostedService<CommandPollingWorker>();
builder.Services.AddHostedService<SessionAgentLauncherWorker>();
builder.Services.AddHostedService<UpdateWorker>();

await builder.Build().RunAsync();
