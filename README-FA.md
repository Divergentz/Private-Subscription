# اشتراک خصوصی و خودکار

این پروژه دو بخش دارد:

1. **مخزن خصوصی GitHub** که منابع مجاز شما را هر ۱۵ دقیقه خوانده، لینک‌ها را استخراج و در `sub.txt` ذخیره می‌کند.
2. **Cloudflare Worker** که فقط با کلید محرمانه، محتوای `sub.txt` را از مخزن خصوصی تحویل می‌دهد.

## نکته مهم درباره «اختصاصی»

این سامانه فقط **دسترسی به لینک اشتراک** را خصوصی می‌کند. کانفیگ‌ها یا سرورهای داخل آن فقط وقتی واقعاً اختصاصی‌اند که VPS، دامنه و سرویس مبدا تحت مالکیت یا کنترل شما باشند.

## ۱. ساخت مخزن GitHub

یک مخزن **Private** بسازید و تمام فایل‌های این پوشه را در آن Upload کنید.

در GitHub به مسیر زیر بروید:

`Settings → Secrets and variables → Actions → New repository secret`

یک Secret با نام زیر بسازید:

`SOURCE_URLS`

مقدار آن باید فهرست URLهای مجاز باشد؛ هر URL در یک خط:

```text
https://example.com/source-one.txt
https://example.com/source-two
```

فقط منابعی را وارد کنید که مجاز به استفاده و بازنشرشان هستید.

سپس از تب `Actions`، گردش‌کار `Update private subscription` را یک بار دستی اجرا کنید. پس از اجرا باید فایل‌های `sub.txt` و `metadata.json` ایجاد یا به‌روزرسانی شوند.

## ۲. ایجاد توکن GitHub

یک Fine-grained personal access token بسازید که:

- فقط به همین مخزن خصوصی دسترسی داشته باشد.
- Repository permission مربوط به `Contents` روی `Read-only` باشد.

توکن را در فایل یا کد ذخیره نکنید.

## ۳. استقرار Cloudflare Worker

داخل پوشه `worker`، مقادیر زیر را در `wrangler.toml` اصلاح کنید:

```toml
GH_OWNER = "نام کاربری گیت‌هاب"
GH_REPO = "نام مخزن خصوصی"
GH_BRANCH = "main"
```

سپس Node.js را نصب کرده و فرمان‌های زیر را اجرا کنید:

```bash
cd worker
npm install
npx wrangler login
npx wrangler secret put GH_TOKEN
npx wrangler secret put SUBSCRIPTION_KEY
npx wrangler deploy
```

برای `GH_TOKEN`، توکن Read-only مرحله قبل را وارد کنید.

برای `SUBSCRIPTION_KEY` یک مقدار تصادفی طولانی وارد کنید. نمونه تولیدشده برای شروع:

```text
bE-Qda6PvygZkEkrK4DDOgAQjRt0CTdPJC90jCN5R_M
```

بهتر است کلید نهایی را خودتان عوض کنید و در جای امن نگه دارید.

## ۴. لینک نهایی

پس از Deploy، Cloudflare یک آدرس شبیه این می‌دهد:

```text
https://private-v2ray-subscription.YOUR-SUBDOMAIN.workers.dev
```

لینک اشتراک شما خواهد بود:

```text
https://private-v2ray-subscription.YOUR-SUBDOMAIN.workers.dev/sub?key=YOUR_SECRET_KEY
```

این URL را می‌توانید در برنامه‌ای که Subscription URL می‌پذیرد وارد کنید.

## ۵. قطع دسترسی یا تعویض لینک

برای باطل‌کردن لینک قبلی:

```bash
cd worker
npx wrangler secret put SUBSCRIPTION_KEY
npx wrangler deploy
```

یک کلید جدید وارد کنید. لینک قبلی فوراً دیگر معتبر نخواهد بود.

## ۶. محدودیت‌ها

- هر کسی که URL کامل را دریافت کند تا زمان تعویض کلید می‌تواند از آن استفاده کند.
- URL ممکن است در تاریخچه مرورگر، لاگ برنامه یا پیام‌رسان باقی بماند.
- برای فروش واقعی به چند مشتری، بهتر است برای هر مشتری کلید مستقل، تاریخ انقضا، محدودیت دستگاه و امکان ابطال جداگانه طراحی شود.
- این پروژه سلامت، سرعت یا امنیت سرورهای جمع‌آوری‌شده را تضمین نمی‌کند.
- عمومی‌بودن یک کانفیگ به معنی مجازبودن فروش مجدد آن نیست.

## اجرای محلی

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
copy sources.example.txt sources.txt   # Windows
# cp sources.example.txt sources.txt   # Linux/macOS
python collector.py
```
