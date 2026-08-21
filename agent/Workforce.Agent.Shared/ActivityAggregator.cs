namespace Workforce.Agent.Shared;

public sealed class ActivityAggregator
{
    private TimeSpan _maxEventDuration;
    private readonly TimeSpan _minimumEventDuration;
    private ActivitySample? _current;
    private LocalActivityEvent? _pendingShort;
    private DateTimeOffset _startedAt;
    private DateTimeOffset _lastCapturedAt;
    private int _keystrokes;
    private int _clicks;
    private int _mouseDistance;

    public ActivityAggregator(TimeSpan? maxEventDuration = null, TimeSpan? minimumEventDuration = null)
    {
        _maxEventDuration = maxEventDuration ?? TimeSpan.FromSeconds(60);
        _minimumEventDuration = minimumEventDuration ?? TimeSpan.FromSeconds(5);
    }

    public IReadOnlyList<LocalActivityEvent> Add(ActivitySample sample)
    {
        var completed = new List<LocalActivityEvent>(2);
        var effectiveStart = sample.State == ActivityStates.Idle
            ? sample.CapturedAt - sample.IdleDuration
            : sample.CapturedAt;

        if (_current is null)
        {
            Start(sample, effectiveStart);
            return completed;
        }

        if (sample.CapturedAt < _lastCapturedAt)
            return completed;

        if (sample.State == ActivityStates.Idle && _current.State != ActivityStates.Idle)
        {
            var idleStart = Max(_startedAt, effectiveStart);
            AddCompleted(completed, Complete(idleStart));
            Start(sample, idleStart);
            return completed;
        }

        if (!SameActivity(_current, sample))
        {
            AddCompleted(completed, Complete(sample.CapturedAt));
            Start(sample, sample.CapturedAt);
            return completed;
        }

        _lastCapturedAt = sample.CapturedAt;
        AddInput(sample);
        if (sample.CapturedAt - _startedAt >= _maxEventDuration)
        {
            AddCompleted(completed, Complete(sample.CapturedAt));
            Start(sample, sample.CapturedAt);
        }
        return completed;
    }

    public void UpdateMaxEventDuration(TimeSpan value)
    {
        if (value >= TimeSpan.FromSeconds(5) && value <= TimeSpan.FromMinutes(5))
            _maxEventDuration = value;
    }

    public IReadOnlyList<LocalActivityEvent> Flush(DateTimeOffset endedAt)
    {
        var result = new List<LocalActivityEvent>(2);
        if (_current is not null)
            AddCompleted(result, Complete(endedAt));
        _current = null;
        if (_pendingShort is not null)
        {
            result.Add(_pendingShort);
            _pendingShort = null;
        }
        return result;
    }

    private void Start(ActivitySample sample, DateTimeOffset startedAt)
    {
        _current = sample;
        _startedAt = startedAt;
        _lastCapturedAt = sample.CapturedAt;
        _keystrokes = sample.Keystrokes;
        _clicks = sample.Clicks;
        _mouseDistance = sample.MouseDistance;
    }

    private LocalActivityEvent Complete(DateTimeOffset endedAt)
    {
        var current = _current ?? throw new InvalidOperationException("No current activity");
        return new LocalActivityEvent(
            Guid.NewGuid(),
            _startedAt.ToUniversalTime(),
            endedAt.ToUniversalTime(),
            current.State,
            current.ProcessName,
            current.AppName,
            current.WindowTitle,
            current.UrlDomain,
            current.UrlPath,
            current.WindowsSessionId,
            current.IsRemote,
            _keystrokes,
            _clicks,
            _mouseDistance,
            current.WindowsSid,
            current.WindowsUsername);
    }

    private void AddInput(ActivitySample sample)
    {
        _keystrokes = Math.Min(int.MaxValue, _keystrokes + Math.Max(0, sample.Keystrokes));
        _clicks = Math.Min(int.MaxValue, _clicks + Math.Max(0, sample.Clicks));
        _mouseDistance = Math.Min(int.MaxValue, _mouseDistance + Math.Max(0, sample.MouseDistance));
    }

    private static bool SameActivity(ActivitySample left, ActivitySample right) =>
        left.State == right.State &&
        string.Equals(left.ProcessName, right.ProcessName, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.UrlDomain, right.UrlDomain, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.UrlPath, right.UrlPath, StringComparison.Ordinal);

    private static DateTimeOffset Max(DateTimeOffset left, DateTimeOffset right) => left > right ? left : right;

    private void AddCompleted(ICollection<LocalActivityEvent> target, LocalActivityEvent item)
    {
        if (item.EndedAt <= item.StartedAt) return;
        if (_pendingShort is not null)
        {
            item = item with {
                StartedAt = _pendingShort.StartedAt,
                Keystrokes = Math.Min(int.MaxValue, item.Keystrokes + _pendingShort.Keystrokes),
                Clicks = Math.Min(int.MaxValue, item.Clicks + _pendingShort.Clicks),
                MouseDistance = Math.Min(int.MaxValue, item.MouseDistance + _pendingShort.MouseDistance),
            };
            _pendingShort = null;
        }
        if (item.EndedAt - item.StartedAt < _minimumEventDuration)
            _pendingShort = item;
        else
            target.Add(item);
    }
}
