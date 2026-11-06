"""Trust & legal pages required by Google (Search quality, AdSense) and privacy laws: editorial policy,
privacy policy, terms of use, contact. Plain, honest text — edit it to match how you really work.

These are templates, not legal advice. Review them (ideally with a lawyer) before running ads.
"""
from __future__ import annotations

UPDATED = "2026-11-06"

EDITORIAL = {
    "en": ("Editorial policy", """
<p>Bang Sport Daily publishes news, history and athlete stories about world sport in English, Chinese and Russian.</p>
<h2>How stories are made</h2>
<ul>
<li><strong>Sources first.</strong> Each story starts from reports by established news outlets and official sources. Every story lists its sources at the end.</li>
<li><strong>AI-assisted writing.</strong> Drafts are written with the help of artificial intelligence ({ai_name}) and adapted into Chinese and Russian. We say so on every story.</li>
<li><strong>Human review.</strong> {author} reads every draft, checks the key facts (names, dates, scores, quotes) against the sources, and approves it before publication. Nothing is published automatically.</li>
<li><strong>Original work.</strong> We do not copy articles. Stories are written in our own words, add context and the editor's perspective, and quote other outlets only briefly and with credit.</li>
<li><strong>Photos.</strong> We only use freely licensed photos from Wikimedia Commons, credited to their authors, or our own designed covers. We never use photos from news agencies without a licence, and we do not publish AI-generated images of real people.</li>
</ul>
<h2>What we don't do</h2>
<ul><li>No betting tips, gambling promotion or odds.</li><li>No gossip about athletes' private lives, health or relationships.</li>
<li>No invented quotes, statistics or authors.</li></ul>
<h2>Corrections</h2>
<p>If we get something wrong, we fix it and note the correction at the end of the story. Please report errors via our <a href="contact.html">contact page</a>.</p>"""),
    "zh": ("编辑方针", """
<p>棒体育日报以中文、英文和俄文发布世界体育新闻、历史和人物故事。</p>
<h2>文章如何产生</h2>
<ul>
<li><strong>来源优先。</strong>每篇文章都以权威媒体和官方来源的报道为基础，并在文末列出来源。</li>
<li><strong>AI 辅助写作。</strong>初稿在人工智能（Google Gemini）协助下撰写，并改写为中文和俄文。我们在每篇文章中注明这一点。</li>
<li><strong>人工审核。</strong>{author} 阅读每篇初稿，对照来源核实关键事实（姓名、日期、比分、引语），批准后才会发布。没有任何内容自动发布。</li>
<li><strong>原创内容。</strong>我们不抄袭文章，用自己的语言写作，补充背景和编辑观点，仅简短引用其他媒体并注明出处。</li>
<li><strong>图片。</strong>我们只使用维基共享资源中注明作者的自由授权图片，或自行设计的封面；不使用未经授权的通讯社图片，也不发布真实人物的 AI 生成图片。</li>
</ul>
<h2>我们不做的事</h2>
<ul><li>不提供博彩建议或赔率。</li><li>不传播运动员私生活、健康或感情八卦。</li><li>不编造引语、数据或作者。</li></ul>
<h2>更正</h2><p>如有错误，我们会更正并在文末注明。请通过<a href="contact.html">联系页面</a>告诉我们。</p>"""),
    "ru": ("Редакционная политика", """
<p>Bang Sport Daily публикует новости, исторические материалы и истории спортсменов на русском, английском и китайском языках.</p>
<h2>Как создаются материалы</h2>
<ul>
<li><strong>Сначала источники.</strong> Каждый материал основан на сообщениях авторитетных СМИ и официальных источников; источники указаны в конце.</li>
<li><strong>Помощь ИИ.</strong> Черновики пишутся с помощью искусственного интеллекта ({ai_name}) и адаптируются на китайский и русский. Мы указываем это в каждом материале.</li>
<li><strong>Проверка человеком.</strong> {author} читает каждый черновик, сверяет ключевые факты (имена, даты, счёт, цитаты) с источниками и одобряет его перед публикацией. Ничего не публикуется автоматически.</li>
<li><strong>Оригинальность.</strong> Мы не копируем статьи: пишем своими словами, добавляем контекст и взгляд редактора, цитируем другие СМИ кратко и со ссылкой.</li>
<li><strong>Фото.</strong> Только свободно лицензированные фото с Викисклада с указанием авторов или наши собственные обложки. Мы не используем фото агентств без лицензии и не публикуем сгенерированные ИИ изображения реальных людей.</li>
</ul>
<h2>Чего мы не делаем</h2>
<ul><li>Никаких ставок, прогнозов и коэффициентов.</li><li>Никаких сплетен о личной жизни и здоровье спортсменов.</li><li>Никаких выдуманных цитат, цифр и авторов.</li></ul>
<h2>Исправления</h2><p>Если мы ошиблись, мы исправим материал и отметим это в конце. Сообщите нам через <a href="contact.html">страницу контактов</a>.</p>"""),
}

PRIVACY = {
    "en": ("Privacy policy", """
<p><em>Last updated: {updated}</em></p>
<p>This policy explains what happens to your data when you visit Bang Sport Daily ("we"). The site is run by {author}.</p>
<h2>What we collect</h2>
<p>We do not ask you to create an account and we do not collect your name or email through this site. We do not use our own cookies or analytics at the moment.</p>
<h2>Services that receive technical data</h2>
<ul>
<li><strong>Hosting:</strong> the site is hosted by {host}. Like any web server, the host processes your IP address and browser information to deliver pages and keep them secure.</li>
<li><strong>Photos:</strong> photos are loaded from Wikimedia Commons (upload.wikimedia.org), which receives your IP address when an image loads. See the Wikimedia Foundation privacy policy.</li>
<li><strong>Fonts:</strong> fonts are served from our own site; we do not use Google Fonts.</li>
<li><strong>Share buttons</strong> are plain links. Nothing is sent to social networks unless you click one.</li>
</ul>
<h2>Advertising (if enabled in the future)</h2>
<p>If we show ads, they may be provided by Google AdSense. Google and its partners use cookies to serve ads based on your visits to this and other websites. You can opt out of personalised advertising in <a href="https://adssettings.google.com" rel="noopener" target="_blank">Google Ads Settings</a> or at <a href="https://www.aboutads.info" rel="noopener" target="_blank">www.aboutads.info</a>. Visitors in the EEA, the UK and Switzerland will be asked for consent through a certified consent tool before any such cookies are used. We will update this policy before ads go live.</p>
<h2>Your rights</h2>
<p>Depending on where you live (for example under the GDPR or similar laws) you may have the right to access, correct or delete personal data. Because we hold almost no personal data, most requests concern the services above. Contact us via the <a href="contact.html">contact page</a>.</p>
<h2>Children</h2><p>This site is not directed at children under 13.</p>"""),
    "zh": ("隐私政策", """
<p><em>最后更新：{updated}</em></p>
<p>本政策说明您访问棒体育日报时数据如何处理。本站由 {author} 运营。</p>
<h2>我们收集的信息</h2><p>本站不要求注册，也不通过网站收集您的姓名或邮箱。目前我们不使用自有 Cookie 或统计工具。</p>
<h2>接收技术数据的服务</h2>
<ul><li><strong>托管：</strong>本站由 {host} 托管，服务器会处理您的 IP 地址和浏览器信息以提供页面并保障安全。</li>
<li><strong>图片：</strong>图片从维基共享资源（upload.wikimedia.org）加载，加载时对方会收到您的 IP 地址。</li>
<li><strong>字体：</strong>字体由本站自行提供，不使用 Google Fonts。</li>
<li><strong>分享按钮</strong>为普通链接，只有点击时才会访问社交网站。</li></ul>
<h2>广告（如将来启用）</h2><p>如显示广告，可能由 Google AdSense 提供。Google 及其合作伙伴会使用 Cookie 根据您对本站及其他网站的访问投放广告。您可在 <a href="https://adssettings.google.com" rel="noopener" target="_blank">Google 广告设置</a>中退出个性化广告。来自欧洲经济区、英国和瑞士的访问者将先通过认证的同意工具征得同意。广告上线前我们会更新本政策。</p>
<h2>您的权利</h2><p>根据您所在地区的法律，您可能有权访问、更正或删除个人数据。请通过<a href="contact.html">联系页面</a>与我们联系。</p>"""),
    "ru": ("Политика конфиденциальности", """
<p><em>Обновлено: {updated}</em></p>
<p>Здесь описано, что происходит с вашими данными при посещении Bang Sport Daily. Сайт ведёт {author}.</p>
<h2>Что мы собираем</h2><p>Регистрация не требуется; мы не собираем имя или e-mail через сайт и пока не используем собственные cookie и аналитику.</p>
<h2>Сервисы, получающие технические данные</h2>
<ul><li><strong>Хостинг:</strong> сайт размещён на {host}; сервер обрабатывает IP-адрес и данные браузера для показа страниц и защиты.</li>
<li><strong>Фото:</strong> загружаются с Викисклада (upload.wikimedia.org), который получает ваш IP-адрес.</li>
<li><strong>Шрифты:</strong> размещены на нашем сайте; Google Fonts не используется.</li>
<li><strong>Кнопки «Поделиться»</strong> — обычные ссылки; данные передаются соцсети только при нажатии.</li></ul>
<h2>Реклама (если появится)</h2><p>Реклама может предоставляться Google AdSense; Google и партнёры используют cookie для показа рекламы. Отключить персонализацию можно в <a href="https://adssettings.google.com" rel="noopener" target="_blank">настройках рекламы Google</a>. Посетителей из ЕЭЗ, Великобритании и Швейцарии сначала попросят дать согласие через сертифицированный инструмент. Мы обновим политику до запуска рекламы.</p>
<h2>Ваши права</h2><p>В зависимости от законодательства вы можете запросить доступ, исправление или удаление данных — через <a href="contact.html">страницу контактов</a>.</p>"""),
}

TERMS = {
    "en": ("Terms of use", """
<p><em>Last updated: {updated}</em></p>
<ul>
<li><strong>Information only.</strong> Stories are for general information and entertainment. We work hard to be accurate, but we cannot guarantee that every detail is complete or current. Check important facts with official sources.</li>
<li><strong>Our content.</strong> Text on this site © {year} Bang Sport Daily. You may quote short extracts with a link to the original story. Please do not republish whole articles without permission.</li>
<li><strong>Third-party content.</strong> Photos belong to their authors and are used under the licences shown with each photo. Links to other websites are provided for reference; we are not responsible for their content.</li>
<li><strong>No betting advice.</strong> Nothing on this site is betting or financial advice.</li>
<li><strong>Changes.</strong> We may update these terms; the date above shows the latest version.</li>
</ul>"""),
    "zh": ("使用条款", """
<p><em>最后更新：{updated}</em></p>
<ul><li><strong>仅供参考。</strong>文章仅供一般信息与娱乐用途。我们力求准确，但无法保证所有细节完整或最新，重要事实请以官方来源为准。</li>
<li><strong>本站内容。</strong>本站文字 © {year} 棒体育日报。可引用简短片段并附原文链接，未经许可请勿全文转载。</li>
<li><strong>第三方内容。</strong>图片归原作者所有，按各图片所示授权使用。外部链接仅供参考。</li>
<li><strong>非投注建议。</strong>本站任何内容均不构成投注或理财建议。</li></ul>"""),
    "ru": ("Условия использования", """
<p><em>Обновлено: {updated}</em></p>
<ul><li><strong>Только информация.</strong> Материалы носят информационный характер. Мы стремимся к точности, но не можем гарантировать полноту каждой детали; важные факты проверяйте в официальных источниках.</li>
<li><strong>Наш контент.</strong> Тексты © {year} Bang Sport Daily. Короткие цитаты со ссылкой допускаются; полная перепечатка — только с разрешения.</li>
<li><strong>Сторонний контент.</strong> Фото принадлежат авторам и используются по указанным лицензиям. За содержание внешних сайтов мы не отвечаем.</li>
<li><strong>Не советы по ставкам.</strong> Ничто на сайте не является советом по ставкам или финансам.</li></ul>"""),
}

CONTACT = {
    "en": ("Contact", """<p>Bang Sport Daily is edited by {author} in Phnom Penh, Cambodia.</p>
<p>For corrections, questions, photo credits or takedown requests: {how}</p>
<p>We aim to reply within a few working days. Corrections are made as quickly as possible.</p>"""),
    "zh": ("联系我们", """<p>棒体育日报由 {author} 在柬埔寨金边编辑。</p><p>更正、问题、图片署名或删除请求：{how}</p><p>我们会在几个工作日内回复。</p>"""),
    "ru": ("Контакты", """<p>Bang Sport Daily редактирует {author} (Пномпень, Камбоджа).</p><p>Исправления, вопросы, авторство фото и запросы на удаление: {how}</p><p>Мы отвечаем в течение нескольких рабочих дней.</p>"""),
}

NO_CONTACT = {"en": "(contact address coming soon)", "zh": "（联系方式即将公布）", "ru": "(контакты скоро появятся)"}
