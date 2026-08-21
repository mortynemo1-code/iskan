using Workforce.Agent.Shared;

namespace Workforce.Agent;

public sealed class CurrentActivityState
{
    private string? _value;

    public string? Value => Volatile.Read(ref _value);

    public void Set(string state)
    {
        if (state is ActivityStates.Productive or ActivityStates.Neutral or ActivityStates.Unproductive
            or ActivityStates.Idle or ActivityStates.Locked or ActivityStates.Break)
            Volatile.Write(ref _value, state);
    }
}
