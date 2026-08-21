using Workforce.Agent.Shared;

namespace Workforce.SessionAgent;

public sealed class TrayApplicationContext : ApplicationContext
{
    private readonly NotifyIcon _tray;
    private readonly NativeActivityReader _reader;
    private readonly ActivityAggregator _aggregator;
    private readonly PipeEventSink _sink = new();
    private readonly CancellationTokenSource _stopping = new();
    private readonly Task _collector;
    private string? _lastState;
    private DateTimeOffset _lastStatusSentAt;
    private DateTimeOffset _lastConfigReadAt;
    private AgentRuntimeConfig _config;
    private readonly ToolStripMenuItem _personalTime;
    private readonly SynchronizationContext _uiContext;
    private readonly ScreenshotCapturer _screenshotCapturer = new();
    private DateTimeOffset _nextScreenshotAt = DateTimeOffset.MinValue;
    private string? _previousCapturedState;
    private readonly StreamController _streamController = new();
    private volatile bool _manualScreenshotRequested;
    private readonly DateTimeOffset _startedAt = DateTimeOffset.Now;
    private AgentStatusForm? _statusForm;
    private readonly object _aggregatorGate = new();
    private readonly InputCounter _inputCounter = new();

    public TrayApplicationContext()
    {
        _config = AgentRuntimeConfig.LoadFromDisk();
        _reader = new NativeActivityReader(_config.IdleThresholdSeconds);
        _reader.ApplyConfig(_config);
        _aggregator = new ActivityAggregator(TimeSpan.FromSeconds(_config.BatchIntervalSeconds));
        _personalTime = new ToolStripMenuItem("Личное время / перерыв") { CheckOnClick = true };
        _personalTime.Enabled = _config.PersonalTimeEnabled;
        _personalTime.CheckedChanged += async (_, _) =>
        {
            _reader.IsBreak = _personalTime.Checked;
            await EmitSystemEventAsync(_personalTime.Checked ? "break_start" : "break_end");
        };
        var disclosure = new ToolStripMenuItem("Что собирает система");
        disclosure.Click += (_, _) => ShowDisclosure();
        var openStatus = new ToolStripMenuItem("Открыть статус");
        openStatus.Click += (_, _) => ShowStatus();

        var menu = new ContextMenuStrip();
        menu.Items.Add(new ToolStripMenuItem("Workforce Monitoring") { Enabled = false });
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(openStatus);
        menu.Items.Add(_personalTime);
        menu.Items.Add(disclosure);
        _tray = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = "Workforce Monitoring — сбор активности включён",
            Visible = true,
            ContextMenuStrip = menu,
        };
        _tray.DoubleClick += (_, _) => ShowStatus();
        _uiContext = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
        _streamController.StreamingChanged += streaming => _uiContext.Post(_ =>
        {
            if (streaming)
            {
                _tray.Text = "Workforce Monitoring — идёт трансляция экрана";
                _tray.ShowBalloonTip(5000, "Трансляция экрана началась",
                    "Уполномоченный руководитель подключился к вашему рабочему экрану.", ToolTipIcon.Info);
            }
            else
            {
                _tray.Text = "Workforce Monitoring — сбор активности включён";
            }
        }, null);
        _streamController.ScreenshotRequested += () => _manualScreenshotRequested = true;
        new ConsentManager().EnsureAcceptedAsync(_sink, _config, _stopping.Token).GetAwaiter().GetResult();
        Microsoft.Win32.SystemEvents.PowerModeChanged += OnPowerModeChanged;
        Microsoft.Win32.SystemEvents.SessionEnding += OnSessionEnding;
        Microsoft.Win32.SystemEvents.SessionSwitch += OnSessionSwitch;
        _collector = Task.Run(CollectAsync);
    }

    private void ShowDisclosure() => MessageBox.Show(
        "Система фиксирует активное приложение, заголовок окна, домен и путь сайта без query-параметров, " +
        "периоды активности, простоя и блокировки экрана. Если это включено администратором, " +
        "система периодически делает снимки и транслирует рабочий экран. Во время перерыва, блокировки и вне графика " +
        "скриншоты и трансляция отключены. Содержимое ввода, микрофон и веб-камера не записываются.\n\n" +
        $"Хранение: {_config.PrivacyRetentionNotice}\nОтветственный: {_config.PrivacyContact}",
        "Что собирает система", MessageBoxButtons.OK, MessageBoxIcon.Information);

    private void ShowStatus()
    {
        if (_statusForm is { IsDisposed: false }) { _statusForm.Activate(); return; }
        _statusForm = new AgentStatusForm(
            () => StatusLabel(_lastState ?? ActivityStates.Neutral),
            () => DateTimeOffset.Now - _startedAt,
            () => _sink.LastDeliveryAt is { } at && DateTimeOffset.UtcNow - at < TimeSpan.FromMinutes(2) ? "служба агента доступна" : "ожидание связи со службой",
            () => _personalTime.Checked = !_personalTime.Checked,
            ShowDisclosure,
            () => EmitSystemEventAsync("diagnostic_requested_by_employee"));
        _statusForm.Show();
    }

    private async void OnPowerModeChanged(object sender, Microsoft.Win32.PowerModeChangedEventArgs args)
    {
        if (args.Mode == Microsoft.Win32.PowerModes.Suspend)
        {
            foreach (var item in FlushAggregator(DateTimeOffset.UtcNow)) await _sink.EnqueueEventAsync(item);
            _streamController.Stop();
            await EmitSystemEventAsync("system_suspend");
        }
        else if (args.Mode == Microsoft.Win32.PowerModes.Resume) await EmitSystemEventAsync("system_resume");
    }

    private async void OnSessionEnding(object sender, Microsoft.Win32.SessionEndingEventArgs args)
    {
        foreach (var item in FlushAggregator(DateTimeOffset.UtcNow)) await _sink.EnqueueEventAsync(item);
        await EmitSystemEventAsync("shutdown");
    }

    private async void OnSessionSwitch(object sender, Microsoft.Win32.SessionSwitchEventArgs args)
    {
        if (args.Reason == Microsoft.Win32.SessionSwitchReason.SessionLock) await EmitSystemEventAsync("lock");
        if (args.Reason == Microsoft.Win32.SessionSwitchReason.SessionUnlock) await EmitSystemEventAsync("unlock");
        if (args.Reason == Microsoft.Win32.SessionSwitchReason.RemoteDisconnect) await EmitSystemEventAsync("rdp_disconnect");
        if (args.Reason == Microsoft.Win32.SessionSwitchReason.RemoteConnect) await EmitSystemEventAsync("rdp_connect");
    }

    private Task EmitSystemEventAsync(string code) => _sink.EnqueueSystemEventAsync(new LocalSystemEvent(
        code, DateTimeOffset.UtcNow, System.Diagnostics.Process.GetCurrentProcess().SessionId,
        new Dictionary<string, object?> { ["timezone"] = TimeZoneInfo.Local.Id, ["utc_offset_minutes"] = (int)TimeZoneInfo.Local.GetUtcOffset(DateTimeOffset.Now).TotalMinutes })).AsTask();

    private IReadOnlyList<LocalActivityEvent> FlushAggregator(DateTimeOffset endedAt)
    {
        lock (_aggregatorGate) return _aggregator.Flush(endedAt);
    }

    private async Task CollectAsync()
    {
        try
        {
            while (!_stopping.IsCancellationRequested)
            {
                if (DateTimeOffset.UtcNow - _lastConfigReadAt >= TimeSpan.FromSeconds(30))
                {
                    _config = AgentRuntimeConfig.LoadFromDisk();
                    _reader.ApplyConfig(_config);
                    lock (_aggregatorGate) _aggregator.UpdateMaxEventDuration(TimeSpan.FromSeconds(_config.BatchIntervalSeconds));
                    _uiContext.Post(_ =>
                    {
                        _personalTime.Enabled = _config.PersonalTimeEnabled;
                        if (!_personalTime.Enabled) _personalTime.Checked = false;
                    }, null);
                    _lastConfigReadAt = DateTimeOffset.UtcNow;
                }
                var input = _inputCounter.SnapshotAndReset();
                var sample = _reader.Capture() with { Keystrokes = input.Keystrokes, Clicks = input.Clicks, MouseDistance = input.MouseDistance };
                var withinSchedule = _config.IsWithinCollectionWindow(sample.CapturedAt);
                await _streamController.PollAsync(withinSchedule, _stopping.Token);
                if (!withinSchedule || sample.State is ActivityStates.Break or ActivityStates.Locked)
                    _streamController.Stop();
                if (withinSchedule || _config.CollectOutsideScheduleActivity)
                {
                    IReadOnlyList<LocalActivityEvent> completed;
                    lock (_aggregatorGate) completed = _aggregator.Add(sample);
                    foreach (var activityEvent in completed)
                        await _sink.EnqueueEventAsync(activityEvent, _stopping.Token);
                }
                if (sample.State != _lastState || sample.CapturedAt - _lastStatusSentAt >= TimeSpan.FromSeconds(10))
                {
                    await _sink.EnqueueStatusAsync(sample.State, _stopping.Token);
                    _lastState = sample.State;
                    _lastStatusSentAt = sample.CapturedAt;
                }
                if (!_streamController.IsStreaming)
                    _tray.Text = $"Workforce Monitoring — {StatusLabel(sample.State)}";
                var enteredUnproductive = _config.ScreenshotOnUnproductive &&
                    sample.State == ActivityStates.Unproductive && _previousCapturedState != ActivityStates.Unproductive;
                if (_config.ScreenshotEnabled &&
                    withinSchedule &&
                    sample.State is not ActivityStates.Break and not ActivityStates.Locked &&
                    (sample.CapturedAt >= _nextScreenshotAt || enteredUnproductive || _manualScreenshotRequested))
                {
                    try
                    {
                        foreach (var screenshot in _screenshotCapturer.Capture(sample, _config))
                            await _sink.EnqueueScreenshotAsync(screenshot, _stopping.Token);
                    }
                    catch (Exception)
                    {
                        // Capture failure must never interrupt activity collection.
                    }
                    ScheduleNextScreenshot(sample.CapturedAt);
                    _manualScreenshotRequested = false;
                }
                _previousCapturedState = sample.State;
                await Task.Delay(TimeSpan.FromSeconds(_config.ActivityPollIntervalSeconds), _stopping.Token);
            }
        }
        catch (OperationCanceledException) when (_stopping.IsCancellationRequested) { }
    }

    private void ScheduleNextScreenshot(DateTimeOffset now)
    {
        var interval = _config.ScreenshotIntervalSeconds;
        var offset = _config.ScreenshotRandomOffset ? Random.Shared.Next(-interval / 4, interval / 4 + 1) : 0;
        _nextScreenshotAt = now.AddSeconds(Math.Max(60, interval + offset));
    }

    private static string StatusLabel(string state) => state switch
    {
        ActivityStates.Idle => "простой",
        ActivityStates.Locked => "экран заблокирован",
        ActivityStates.Break => "личное время",
        _ => "активен",
    };

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            Microsoft.Win32.SystemEvents.PowerModeChanged -= OnPowerModeChanged;
            Microsoft.Win32.SystemEvents.SessionEnding -= OnSessionEnding;
            Microsoft.Win32.SystemEvents.SessionSwitch -= OnSessionSwitch;
            _stopping.Cancel();
            foreach (var final in FlushAggregator(DateTimeOffset.UtcNow))
                _sink.EnqueueEventAsync(final).AsTask().GetAwaiter().GetResult();
            try { _collector.GetAwaiter().GetResult(); } catch (OperationCanceledException) { }
            _sink.DisposeAsync().AsTask().GetAwaiter().GetResult();
            _streamController.Dispose();
            _inputCounter.Dispose();
            _tray.Visible = false;
            _tray.Dispose();
            _stopping.Dispose();
        }
        base.Dispose(disposing);
    }
}
