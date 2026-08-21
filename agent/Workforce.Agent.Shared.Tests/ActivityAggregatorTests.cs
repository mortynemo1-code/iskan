using Workforce.Agent.Shared;

namespace Workforce.Agent.Shared.Tests;

public sealed class ActivityAggregatorTests
{
    private static readonly DateTimeOffset Start = new(2026, 8, 20, 9, 0, 0, TimeSpan.Zero);

    [Fact]
    public void Idle_reclassifies_time_from_last_input()
    {
        var aggregator = new ActivityAggregator(TimeSpan.FromMinutes(30));
        aggregator.Add(Sample(Start, ActivityStates.Neutral, TimeSpan.Zero));

        var completed = aggregator.Add(Sample(
            Start.AddMinutes(6),
            ActivityStates.Idle,
            TimeSpan.FromMinutes(5)));

        var active = Assert.Single(completed);
        Assert.Equal(Start, active.StartedAt);
        Assert.Equal(Start.AddMinutes(1), active.EndedAt);
        Assert.Equal(ActivityStates.Neutral, active.State);

        var idle = Assert.Single(aggregator.Flush(Start.AddMinutes(7)));
        Assert.Equal(Start.AddMinutes(1), idle.StartedAt);
        Assert.Equal(ActivityStates.Idle, idle.State);
    }

    [Fact]
    public void Long_activity_is_rolled_over_for_regular_upload()
    {
        var aggregator = new ActivityAggregator(TimeSpan.FromSeconds(60));
        aggregator.Add(Sample(Start, ActivityStates.Neutral, TimeSpan.Zero));

        var completed = aggregator.Add(Sample(Start.AddSeconds(60), ActivityStates.Neutral, TimeSpan.Zero));

        var item = Assert.Single(completed);
        Assert.Equal(60, (item.EndedAt - item.StartedAt).TotalSeconds);
    }

    [Fact]
    public void Process_change_closes_previous_event()
    {
        var aggregator = new ActivityAggregator();
        aggregator.Add(Sample(Start, ActivityStates.Neutral, TimeSpan.Zero, "winword.exe"));

        var completed = aggregator.Add(Sample(
            Start.AddSeconds(10),
            ActivityStates.Neutral,
            TimeSpan.Zero,
            "chrome.exe"));

        Assert.Equal("winword.exe", Assert.Single(completed).ProcessName);
    }

    [Fact]
    public void Short_event_is_attached_to_next_activity()
    {
        var aggregator = new ActivityAggregator(TimeSpan.FromMinutes(30), TimeSpan.FromSeconds(5));
        aggregator.Add(Sample(Start, ActivityStates.Neutral, TimeSpan.Zero, "popup.exe"));
        Assert.Empty(aggregator.Add(Sample(
            Start.AddSeconds(3), ActivityStates.Neutral, TimeSpan.Zero, "code.exe")));

        var completed = aggregator.Add(Sample(
            Start.AddSeconds(10), ActivityStates.Neutral, TimeSpan.Zero, "chrome.exe"));

        var item = Assert.Single(completed);
        Assert.Equal(Start, item.StartedAt);
        Assert.Equal("code.exe", item.ProcessName);
    }

    [Fact]
    public void Input_intensity_is_summed_without_key_content()
    {
        var aggregator = new ActivityAggregator(TimeSpan.FromMinutes(30));
        aggregator.Add(Sample(Start, ActivityStates.Neutral, TimeSpan.Zero) with { Keystrokes = 4, Clicks = 2, MouseDistance = 120 });
        aggregator.Add(Sample(Start.AddSeconds(5), ActivityStates.Neutral, TimeSpan.Zero) with { Keystrokes = 3, Clicks = 1, MouseDistance = 80 });

        var item = Assert.Single(aggregator.Flush(Start.AddSeconds(10)));
        Assert.Equal(7, item.Keystrokes);
        Assert.Equal(3, item.Clicks);
        Assert.Equal(200, item.MouseDistance);
    }

    private static ActivitySample Sample(
        DateTimeOffset at,
        string state,
        TimeSpan idle,
        string process = "code.exe") =>
        new(at, state, process, process, process, null, null, 1, false, idle);
}
