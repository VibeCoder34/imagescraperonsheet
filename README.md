# Image Scraper on Sheet

Araç ilan sitelerinden fotoğraf URL'lerini, plaka bilgilerini ve isteğe bağlı olarak Car Studio ile işlenmiş görselleri CSV formatında toplayan bir araç seti.

## Ne Yapar?

Proje iki ana bölümden oluşur:

1. **Scraper** — Hedef siteden ilan verilerini çeker ve CSV üretir.
2. **Car Studio pipeline** — Çekilen görselleri Car Studio AI'ya gönderir, Supabase'de takip eder ve işlenmiş URL'leri tekrar CSV'ye yazar.

```
Hedef site  →  Scraper (Python)  →  CSV
                                      ↓
                              submit_jobs.py
                                      ↓
                              Car Studio API
                                      ↓
                         Vercel webhook → Supabase
                                      ↓
                    export / merge → nihai CSV
```

## Gereksinimler

- Python 3.10+
- (Opsiyonel) Car Studio API anahtarı, Supabase projesi, Vercel hesabı

### Python bağımlılıkları

```bash
pip install -r carstudio/requirements.txt
```

Scraper scriptleri standart kütüphane kullanır; ek paket gerekmez.

---

## Bölüm 1: Scraper

Tüm scraper scriptleri `--base-url` ile hedef siteyi belirtmenizi ister. Alternatif olarak `SITE_BASE_URL` ortam değişkeni kullanılabilir.

```bash
export SITE_BASE_URL=https://example.com
python3 scrape_listings.py
```

### `scrape_listing_images.py`

Sadece fotoğraf URL'lerini çeker.

```bash
python3 scrape_listing_images.py --base-url https://example.com
```

**Çıktılar:**
| Dosya | Açıklama |
|-------|----------|
| `images.csv` | Sitemap sırasına göre ilanlar + galeri fotoğrafları |
| `images_by_listing_order.csv` | İlan listesi sayfasındaki görünüm sırasına göre |

**CSV sütunları:** `listing_url`, `listing_id`, `image_index`, `image_url` (+ `listing_order` sıralı dosyada)

### `scrape_listings.py`

Fotoğrafların yanı sıra plaka numarasını da çeker (tek seferde tam veri).

```bash
python3 scrape_listings.py --base-url https://example.com
python3 scrape_listings.py --base-url https://example.com --output listings.csv --output-by-order listings_by_order.csv --delay 0.5
```

**Ek sütun:** `plate_number`

**Site yapılandırması:**

| Parametre | Varsayılan | Açıklama |
|-----------|------------|----------|
| `--base-url` | — | Site kök URL'si (zorunlu) |
| `--listings-path` | `/araclar` | İlan listesi sayfası yolu |
| `--sitemap-path` | `/sitemap/araclar.xml` | Sitemap yolu |
| `--page-param` | `sayfa` | Sayfalama query parametresi |

### `scrape_plates.py`

Mevcut bir images CSV'sine plaka bilgisi ekler.

```bash
python3 scrape_plates.py --input images.csv --output images_with_plates.csv
```

---

## Bölüm 2: Car Studio Pipeline

Bu bölüm, CSV'deki ham fotoğrafları [Car Studio AI](https://carstudio.ai) üzerinden stüdyo kalitesinde işlemek için kullanılır.

### Kurulum

1. **Supabase** — `carstudio/supabase/schema.sql` dosyasını Supabase SQL Editor'de çalıştırın.
2. **Ortam değişkenleri** — `carstudio/.env.example` dosyasını `carstudio/.env` olarak kopyalayın ve doldurun:

   | Değişken | Açıklama |
   |----------|----------|
   | `CARSTUDIO_API_KEY` | Car Studio API anahtarı |
   | `CARSTUDIO_BASE_URL` | API base URL (varsayılan: `https://tokyo.carstudio.ai`) |
   | `CARSTUDIO_CALLBACK_URL` | Vercel webhook URL'si |
   | `CARSTUDIO_BACKGROUND_URL` | Arka plan görseli URL'si (opsiyonel) |
   | `SUPABASE_URL` | Supabase proje URL'si |
   | `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key |
   | `INPUT_CSV` | Gönderilecek kaynak CSV yolu |
   | `JOB_ID_PREFIX` | Transaction ID öneki (varsayılan: `listing`) |

3. **Webhook (Vercel)** — Car Studio iş bitince sonucu bildirmek için:

   ```bash
   cd carstudio/webhook
   npm install
   vercel deploy
   ```

   Vercel ortam değişkenlerine `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `CARSTUDIO_API_KEY` ekleyin. Dönen URL'yi `CARSTUDIO_CALLBACK_URL` olarak `.env`'e yazın.

### Scriptler

#### `submit_jobs.py` — İşleri gönder

CSV'deki her ilanın fotoğraflarını Car Studio'ya async olarak gönderir. 25'ten fazla fotoğrafı olan ilanlar otomatik olarak batch'lere bölünür.

```bash
cd carstudio
python3 submit_jobs.py
```

- Supabase'e `carstudio_jobs` ve `carstudio_images` kayıtları yazar
- Başarısız işleri yeniden deneyebilir (`FAILED` → reset)
- Test için `LIMIT_LISTINGS=2` ortam değişkeni kullanılabilir

#### `check_status.py` — Durum kontrolü

Supabase ve Car Studio API üzerinden son işlerin durumunu listeler.

```bash
python3 check_status.py
```

#### `sync_completed_jobs.py` — Eksik URL'leri tamamla

Webhook kaçırmış veya gecikmiş işler için Car Studio search API'sinden işlenmiş görsel URL'lerini çekip Supabase'e yazar.

```bash
python3 sync_completed_jobs.py
```

#### `export_results.py` — Supabase → CSV

Tüm iş ve görsel kayıtlarını tek bir CSV'ye aktarır.

```bash
python3 export_results.py
```

#### `merge_processed_to_csv.py` — Kaynak CSV ile birleştir

Orijinal scraper CSV'sine `processed_image_url` sütunu ekler.

```bash
python3 merge_processed_to_csv.py
```

---

## Tipik İş Akışı

```bash
# 1. Siteden veri çek
python3 scrape_listings.py --base-url https://example.com

# 2. Car Studio'ya gönder (carstudio/.env hazır olmalı)
cd carstudio && python3 submit_jobs.py

# 3. İşlerin bitmesini bekle (webhook otomatik günceller)
python3 check_status.py

# 4. Gerekirse eksik URL'leri senkronize et
python3 sync_completed_jobs.py

# 5. Nihai CSV'yi üret
python3 merge_processed_to_csv.py
```

---

## Proje Yapısı

```
.
├── scrape_listing_images.py       # Sadece fotoğraf scraper
├── scrape_listings.py             # Fotoğraf + plaka scraper
├── scrape_plates.py               # Mevcut CSV'ye plaka ekle
├── carstudio/
│   ├── submit_jobs.py             # Car Studio'ya iş gönder
│   ├── check_status.py            # Durum sorgula
│   ├── sync_completed_jobs.py     # Eksik sonuçları çek
│   ├── export_results.py          # Supabase → CSV
│   ├── merge_processed_to_csv.py  # İşlenmiş URL'leri birleştir
│   ├── requirements.txt
│   ├── .env.example
│   ├── supabase/schema.sql
│   └── webhook/                   # Vercel serverless callback
│       └── api/webhook.js
└── *.csv                          # Üretilen çıktılar (gitignore'da)
```

---

## Notlar

- Scraper istekler arasında gecikme kullanır (`0.3–0.5 sn`) — `--delay` ile ayarlanabilir.
- Car Studio işleri asenkron çalışır; sonuçlar webhook veya `sync_completed_jobs.py` ile alınır.
- `.env` dosyaları repoya dahil edilmez; API anahtarlarınızı paylaşmayın.
- CSV çıktıları `.gitignore` ile repodan hariç tutulur.
