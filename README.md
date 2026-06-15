# Image Scraper on Sheet

Otomol (`https://www.otomol.com/araclar`) ikinci el araç ilanlarından fotoğraf URL'lerini, plaka bilgilerini ve isteğe bağlı olarak Car Studio ile işlenmiş görselleri CSV formatında toplayan bir araç seti.

## Ne Yapar?

Proje iki ana bölümden oluşur:

1. **Scraper** — Otomol sitesinden ilan verilerini çeker ve CSV üretir.
2. **Car Studio pipeline** — Çekilen görselleri Car Studio AI'ya gönderir, Supabase'de takip eder ve işlenmiş URL'leri tekrar CSV'ye yazar.

```
Otomol.com  →  Scraper (Python)  →  CSV
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

## Bölüm 1: Otomol Scraper

### `scrape_otomol_images.py`

Sadece fotoğraf URL'lerini çeker.

```bash
python3 scrape_otomol_images.py
```

**Çıktılar:**
| Dosya | Açıklama |
|-------|----------|
| `otomol_images.csv` | Sitemap sırasına göre ilanlar + galeri fotoğrafları |
| `otomol_images_by_listing_order.csv` | `/araclar` sayfasındaki görünüm sırasına göre |

**CSV sütunları:** `listing_url`, `listing_id`, `image_index`, `image_url` (+ `listing_order` sıralı dosyada)

### `scrape_otomol.py`

Fotoğrafların yanı sıra plaka numarasını da çeker (tek seferde tam veri).

```bash
python3 scrape_otomol.py
python3 scrape_otomol.py --output otomol_listings.csv --output-by-order otomol_listings_by_order.csv --delay 0.5
```

**Çıktılar:**
| Dosya | Açıklama |
|-------|----------|
| `otomol_listings_2026-06-09.csv` | Sitemap sırası |
| `otomol_listings_by_order_2026-06-09.csv` | Site görünüm sırası |

**Ek sütun:** `plate_number`

### `scrape_otomol_plates.py`

Mevcut bir images CSV'sine plaka bilgisi ekler (ayrı adım olarak).

```bash
python3 scrape_otomol_plates.py --input otomol_images.csv --output otomol_images_with_plates.csv
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

**Çıktı sütunları:** `listing_order`, `listing_url`, `listing_id`, `plate_number`, `batch_index`, `job_status`, `image_index`, `original_image_url`, `processed_image_url`, `car_studio_id`

#### `merge_processed_to_csv.py` — Kaynak CSV ile birleştir

Orijinal scraper CSV'sine `processed_image_url` sütunu ekler.

```bash
python3 merge_processed_to_csv.py
```

---

## Tipik İş Akışı

```bash
# 1. Otomol'dan veri çek
python3 scrape_otomol.py

# 2. Car Studio'ya gönder (carstudio/.env hazır olmalı)
cd carstudio && python3 submit_jobs.py

# 3. İşlerin bitmesini bekle (webhook otomatik günceller)
python3 check_status.py

# 4. Gerekirse eksik URL'leri senkronize et
python3 sync_completed_jobs.py

# 5. Nihai CSV'yi üret
python3 merge_processed_to_csv.py
# veya
python3 export_results.py
```

---

## Proje Yapısı

```
.
├── scrape_otomol_images.py      # Sadece fotoğraf scraper
├── scrape_otomol.py               # Fotoğraf + plaka scraper
├── scrape_otomol_plates.py        # Mevcut CSV'ye plaka ekle
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
└── *.csv                          # Örnek çıktı dosyaları
```

---

## Notlar

- Scraper istekler arasında gecikme kullanır (`0.3–0.5 sn`) — siteye saygılı davranmak için `--delay` ile ayarlanabilir.
- Car Studio işleri asenkron çalışır; sonuçlar webhook veya `sync_completed_jobs.py` ile alınır.
- `.env` dosyaları repoya dahil edilmez; API anahtarlarınızı paylaşmayın.
