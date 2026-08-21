-- Built-in classification catalog. Domain aliases are explicit entries so administrators can
-- override each position independently; together with desktop applications this seeds >300 rules.
INSERT INTO categories(code,name,productivity,is_system) VALUES
('communication','Коммуникации','NEUTRAL',true),
('project_management','Управление проектами','PRODUCTIVE',true),
('design','Дизайн','PRODUCTIVE',true),
('finance','Финансы и учёт','PRODUCTIVE',true),
('streaming','Стриминговые сервисы','UNPRODUCTIVE',true),
('games','Игры','UNPRODUCTIVE',true),
('torrents','Торренты','UNPRODUCTIVE',true)
ON CONFLICT(code) DO NOTHING;

WITH app_seed(pattern,category_code) AS (VALUES
('notepad.exe','office'),('notepad++.exe','development'),('winword.exe','office'),('excel.exe','office'),
('powerpnt.exe','office'),('outlook.exe','communication'),('onenote.exe','office'),('msaccess.exe','office'),
('mspub.exe','office'),('libreoffice.exe','office'),('soffice.exe','office'),('wps.exe','office'),
('code.exe','development'),('devenv.exe','development'),('rider64.exe','development'),('idea64.exe','development'),
('pycharm64.exe','development'),('webstorm64.exe','development'),('phpstorm64.exe','development'),('clion64.exe','development'),
('goland64.exe','development'),('datagrip64.exe','development'),('androidstudio64.exe','development'),('eclipse.exe','development'),
('netbeans64.exe','development'),('sublime_text.exe','development'),('atom.exe','development'),('vim.exe','development'),
('nvim.exe','development'),('powershell.exe','development'),('pwsh.exe','development'),('cmd.exe','development'),
('windowsterminal.exe','development'),('putty.exe','development'),('winscp.exe','development'),('filezilla.exe','development'),
('docker desktop.exe','development'),('postman.exe','development'),('insomnia.exe','development'),('dbeaver.exe','development'),
('pgadmin4.exe','development'),('ssms.exe','development'),('gitkraken.exe','development'),('sourcetree.exe','development'),
('figma.exe','design'),('photoshop.exe','design'),('illustrator.exe','design'),('indesign.exe','design'),
('afterfx.exe','design'),('premiere pro.exe','design'),('blender.exe','design'),('sketch.exe','design'),
('teams.exe','communication'),('slack.exe','communication'),('telegram.exe','communication'),('zoom.exe','communication'),
('skype.exe','communication'),('discord.exe','communication'),('mattermost.exe','communication'),('viber.exe','communication'),
('1cv8.exe','finance'),('1cv7.exe','finance'),('sbis.exe','finance'),('kontur.exe','finance'),
('steam.exe','games'),('epicgameslauncher.exe','games'),('battle.net.exe','games'),('riotclientservices.exe','games'),
('utorrent.exe','torrents'),('qbittorrent.exe','torrents'),('bittorrent.exe','torrents'),('transmission-qt.exe','torrents')
), numbered AS (
  SELECT pattern,category_code,1000+row_number() OVER(ORDER BY category_code,pattern) AS priority FROM app_seed
)
INSERT INTO rules(priority,match_field,match_type,pattern,category_id)
SELECT numbered.priority,'process_name','exact',numbered.pattern,c.id
FROM numbered JOIN categories c ON c.code=numbered.category_code
WHERE NOT EXISTS(SELECT 1 FROM rules r WHERE r.match_field='process_name' AND lower(r.pattern)=lower(numbered.pattern));

WITH domain_seed(domain,category_code) AS (VALUES
('github.com','development'),('gitlab.com','development'),('bitbucket.org','development'),('stackoverflow.com','development'),
('developer.mozilla.org','development'),('learn.microsoft.com','development'),('docs.python.org','development'),('docs.oracle.com','development'),
('npmjs.com','development'),('pypi.org','development'),('nuget.org','development'),('docker.com','development'),
('kubernetes.io','development'),('terraform.io','development'),('aws.amazon.com','development'),('cloud.google.com','development'),
('portal.azure.com','development'),('grafana.com','development'),('sentry.io','development'),('atlassian.net','project_management'),
('jira.com','project_management'),('trello.com','project_management'),('asana.com','project_management'),('monday.com','project_management'),
('clickup.com','project_management'),('notion.so','project_management'),('miro.com','project_management'),('linear.app','project_management'),
('office.com','office'),('microsoft365.com','office'),('docs.google.com','office'),('sheets.google.com','office'),
('slides.google.com','office'),('drive.google.com','office'),('dropbox.com','office'),('box.com','office'),
('figma.com','design'),('canva.com','design'),('adobe.com','design'),('behance.net','design'),
('slack.com','communication'),('teams.microsoft.com','communication'),('zoom.us','communication'),('web.telegram.org','communication'),
('web.whatsapp.com','communication'),('meet.google.com','communication'),('mail.ru','communication'),('outlook.office.com','communication'),
('vk.com','social'),('ok.ru','social'),('facebook.com','social'),('instagram.com','social'),
('x.com','social'),('twitter.com','social'),('reddit.com','social'),('pinterest.com','social'),
('tiktok.com','video'),('youtube.com','video'),('rutube.ru','video'),('dzen.ru','video'),
('twitch.tv','streaming'),('vimeo.com','streaming'),('netflix.com','streaming'),('kinopoisk.ru','streaming'),
('ivi.ru','streaming'),('okko.tv','streaming'),('premier.one','streaming'),('start.ru','streaming'),
('spotify.com','streaming'),('music.yandex.ru','streaming'),('soundcloud.com','streaming'),('last.fm','streaming'),
('steampowered.com','games'),('epicgames.com','games'),('battle.net','games'),('riotgames.com','games'),
('playstation.com','games'),('xbox.com','games'),('miniclip.com','games'),('itch.io','games')
), aliases(pattern,category_code) AS (
  SELECT domain,category_code FROM domain_seed
  UNION ALL SELECT 'www.'||domain,category_code FROM domain_seed
  UNION ALL SELECT 'm.'||domain,category_code FROM domain_seed
), numbered AS (
  SELECT pattern,category_code,2000+row_number() OVER(ORDER BY category_code,pattern) AS priority FROM aliases
)
INSERT INTO rules(priority,match_field,match_type,pattern,category_id)
SELECT numbered.priority,'url_domain','exact',numbered.pattern,c.id
FROM numbered JOIN categories c ON c.code=numbered.category_code
WHERE NOT EXISTS(SELECT 1 FROM rules r WHERE r.match_field='url_domain' AND lower(r.pattern)=lower(numbered.pattern));

-- Short-video routes must outrank their neutral/general parent domains.
WITH short_seed(priority,pattern) AS (VALUES
(1,'youtube.com/shorts'),(2,'instagram.com/reels'),(3,'facebook.com/reels'),
(4,'vk.com/clips'),(5,'ok.ru/video/shorts'),(6,'dzen.ru/shorts'),(7,'rutube.ru/shorts'))
INSERT INTO rules(priority,match_field,match_type,pattern,category_id)
SELECT s.priority,'url_full','contains',s.pattern,c.id FROM short_seed s JOIN categories c ON c.code='video'
WHERE NOT EXISTS(SELECT 1 FROM rules r WHERE r.match_field='url_full' AND lower(r.pattern)=lower(s.pattern));
