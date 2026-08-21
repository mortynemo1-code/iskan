namespace Workforce.SessionAgent;

public sealed class AgentStatusForm : Form
{
    private readonly Label _state = new() { AutoSize = true, Font = new Font(SystemFonts.DefaultFont, FontStyle.Bold) };
    private readonly Label _worked = new() { AutoSize = true };
    private readonly Label _connection = new() { AutoSize = true };
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 1000 };

    public AgentStatusForm(
        Func<string> state,
        Func<TimeSpan> worked,
        Func<string> connection,
        Action toggleBreak,
        Action showDisclosure,
        Func<Task> sendLogs)
    {
        Text = "Workforce Monitoring";
        Width = 520;
        Height = 330;
        MinimumSize = new Size(480, 300);
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        var title = new Label { Text = "Учёт рабочего времени включён", AutoSize = true, Font = new Font(SystemFonts.DefaultFont.FontFamily, 15, FontStyle.Bold) };
        var productivity = new Label { Text = "Продуктивность: доступна в личном кабинете, если разрешена организацией", AutoSize = true, ForeColor = Color.DimGray };
        var version = new Label { Text = $"Версия агента: {Application.ProductVersion}", AutoSize = true, ForeColor = Color.DimGray };
        var breakButton = new Button { Text = "Личное время / перерыв", AutoSize = true };
        breakButton.Click += (_, _) => toggleBreak();
        var disclosure = new Button { Text = "Что собирает система", AutoSize = true };
        disclosure.Click += (_, _) => showDisclosure();
        var logs = new Button { Text = "Отправить логи в поддержку", AutoSize = true };
        logs.Click += async (_, _) =>
        {
            logs.Enabled = false;
            try { await sendLogs(); MessageBox.Show("Запрос на отправку диагностики передан службе.", Text); }
            catch (Exception exception) { MessageBox.Show(exception.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Warning); }
            finally { logs.Enabled = true; }
        };
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(24), AutoScroll = true };
        layout.Controls.Add(title);
        layout.Controls.Add(new Label { Text = "Текущий статус:", AutoSize = true, Margin = new Padding(3, 18, 3, 0) });
        layout.Controls.Add(_state);
        layout.Controls.Add(_worked);
        layout.Controls.Add(productivity);
        layout.Controls.Add(_connection);
        layout.Controls.Add(version);
        var buttons = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 18, 0, 0) };
        buttons.Controls.AddRange([breakButton, disclosure, logs]);
        layout.Controls.Add(buttons);
        Controls.Add(layout);
        void refresh()
        {
            _state.Text = state();
            _worked.Text = $"Сессия сбора сегодня: {worked():hh\\:mm\\:ss}";
            _connection.Text = $"Связь: {connection()}";
        }
        _timer.Tick += (_, _) => refresh();
        Shown += (_, _) => { refresh(); _timer.Start(); };
        FormClosed += (_, _) => _timer.Stop();
    }
}
