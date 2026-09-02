# nezih-x-auto

3 X hesabına (nezihsport / nezihsosyal / nezihbet) otomatik görsel üretip
zamanlanmış paylaşım yapar. **Toplam maliyet: 0 TL.**

```
GitHub Actions (ücretsiz cron, 6 saatte bir)
   │
   ├─ RSS / içerik havuzundan yeni içerik al
   ├─ Nezihbet markalı görsel üret (PIL)  ─────► docs/img/*.jpg
   │                                              │ commit
   │                                              ▼
   │                                    GitHub Pages (ücretsiz HTTPS host)
   │                                              │
   └─ Görsel adresi 200 dönüyorsa ───────────────►│
        Buffer'a zamanlanmış post yarat            │
                     │                             │
                     ▼                             │
              Buffer (ücretsiz plan) ◄─────────────┘
                     │  görseli bu adresten çeker
                     ▼
                  X hesapları
```

## Neden bu mimari

**X API'si artık ücretsiz değil.** 6 Şubat 2026'dan beri yeni geliştiriciler
için free tier yok; pay-per-use'da post başına $0.015, link içeren postta
$0.20. Buffer bu maliyeti kendi kurumsal anlaşmasından karşılıyor, biz
ücretsiz planından yararlanıyoruz.

**Buffer ücretsiz planı:** 3 kanal, kanal başına aynı anda **10 bekleyen
post**. Bu aylık bir kota *değil* — post yayınlandığı anda slot boşalır.
Yani ayda kaç paylaşım yapacağınızın sınırı yok; sadece kuyrukta aynı anda
10'dan fazla bekleyen post olamaz. `queue_target: 8` ile güvenli tampon
bırakılıyor.

**Buffer'ın medya yükleme ucu yok** — görselin herkese açık, kalıcı bir HTTPS
adresinde durmasını ve post yayınlanana kadar orada kalmasını şart koşuyor.
GitHub Pages tam olarak bunu ücretsiz veriyor.

## Kurulum

### 1. Buffer
1. buffer.com'da ücretsiz hesap aç.
2. 3 X hesabını kanal olarak bağla (ücretsiz plan tam 3 kanal veriyor).
3. **Settings → API** → kişisel API anahtarı üret. Ücretsiz planda 1 anahtar
   hakkın var. (Anahtarı yalnızca organizasyon sahibi üretebiliyor — kendi
   hesabında sorun değil.)

### 2. Repo
1. Bu klasörü bir GitHub reposuna yükle. **Public olmalı** — ücretsiz hesapta
   GitHub Pages yalnızca public repoda çalışıyor.
2. **Settings → Secrets and variables → Actions → New repository secret**
   - Ad: `BUFFER_API_KEY`, değer: Buffer anahtarın.
   - Anahtar şifreli saklanır, repoda görünmez, loglarda maskelenir.
3. **Settings → Pages** → Source: `Deploy from a branch`, Branch: `main`,
   klasör: `/docs`. Kaydet. Çıkan adresi `config.yaml > pages_base_url`'e yaz.

### 3. Kanal ID'leri
```bash
pip install -r requirements.txt
export BUFFER_API_KEY=xxx          # Windows PowerShell: $env:BUFFER_API_KEY="xxx"
python -m generator.main probe
```
`probe`, Buffer şemasının kök sorgularını listeler; kanal listesini veren
sorgunun adını oradan görebilirsin. Kanal ID'lerini Buffer arayüzünde bir
kanalı açtığında adres çubuğundan da kopyalayabilirsin. Bulduğun ID'leri
`config.yaml`'daki `buffer_channel_id` alanlarına yaz.

### 4. Test → canlı
```bash
python -m generator.main plan    # hiçbir şey göndermez, ne planlanacağını yazar
python -m generator.main run     # gerçek
```
`plan` görselleri `docs/img/` altına üretir ama Buffer'a dokunmaz ve
`state.json`'ı değiştirmez. Önce bununla metinleri ve zamanlamayı beğen.

Sonra Actions sekmesinden workflow'u elle bir kez tetikle (`workflow_dispatch`),
Buffer'da postların kuyruğa düştüğünü gör. Ondan sonrası otomatik.

## İlk turda hiçbir şey planlanmaz — bu normal

Görsel üretildiği turda henüz GitHub Pages'te yayında değildir. Kod, adresin
gerçekten `200` ve `image/*` döndüğünü doğrulamadan Buffer'a post yaratmaz;
doğrulanmayanlar bir sonraki tura bırakılır. Yani ilk tur görselleri üretir,
ikinci tur (6 saat sonra) planlar. Elle iki kez tetikleyerek hızlandırabilirsin.

## Zamanlamayı ayarlama

`config.yaml` içinde kanal başına:

| Alan | Anlamı |
|---|---|
| `slots` | Günlük yayın saatleri, **Türkiye saati** (`["10:00","19:00"]`) |
| `min_gap_hours` | İki post arası en az boşluk |
| `min_lead_minutes` | En erken "şu andan şu kadar sonra" (görselin yayılma payı) |
| `queue_target` | Kuyrukta tutulacak bekleyen post sayısı (Buffer sınırı 10) |

Örnek: `slots: ["10:00","19:00"]` + `queue_target: 8` → günde 2 paylaşım,
kuyrukta hep ~4 günlük içerik hazır.

## İçerik kaynakları

- `source: rss` → bir RSS beslemesi (nezihsport). Görsel, haberin kendi
  görselinden veya sayfanın `og:image`'ından alınır, üstüne Nezihbet logosu
  ve başlık şeridi basılır.
- `source: pool` → `config.yaml`'daki sabit içerik listesi (nezihsosyal,
  nezihbet). Haber beslemesi olmayan hesaplar için; sırayla paylaşılır.

Şablonlar: `template: news` (arkaplanda fotoğraf) ve `template: text`
(düz markalı gradient kart).

## Logo / marka işareti

Marka logosunda "bet" geçtiği için **varsayılan olarak kapalı** — X'in
gambling/spam filtrelerini tetikleme riski var. Kanal başına:

| Ayar | Sonuç |
|---|---|
| `logo: "none"` | Logo yok (varsayılan) |
| `logo: "brand"` | `assets/logo.png` basılır |
| `logo: "assets/baska.png"` | Belirttiğin dosya |
| `watermark_text: "NEZİH SPOR"` | Logo yerine sağ üstte altın renkli düz metin |

`watermark_text`'i boş bırakırsan görselde hiçbir marka izi kalmaz.

> Logo ayarını değiştirdikten sonra `docs/img/` içindeki eski görselleri sil —
> dosya adı içerikten üretildiği için var olan görsel yeniden çizilmez.

## Güvenlik

Kendi bilgisayarında Python çalıştırmak başlı başına bir açık değil, ama bu
kurulumda GitHub Actions daha güvenli:

- API anahtarı diskte düz metin `config.yaml`'da değil, GitHub'ın şifreli
  Secrets deposunda durur ve log çıktısında otomatik maskelenir.
- Bilgisayarının 7/24 açık kalması gerekmez.
- Repo public ama **içinde sır yok** — anahtar yalnızca çalışma anında ortam
  değişkeni olarak enjekte edilir. Fork'lardan gelen PR'lara secret verilmez.

Tek dikkat: `config.yaml`'a asla anahtar yazma, `state.json` ve `docs/`
dışında bir şey commit'leme.

## Sınırlar

- Buffer ücretsiz: 3 kanal, kanal başına 10 bekleyen post.
- GitHub Actions ücretsiz: public repoda sınırsız dakika.
- GitHub Pages: 1 GB depo, ayda 100 GB trafik. Görseller ~60-90 KB, yani
  pratikte sınıra yaklaşmazsın. Yine de eski görselleri arada temizlemek
  isteyebilirsin.
- Buffer, X'e gönderimi kendi kotasından yapar; çok yüksek hacimde
  sınırlamayla karşılaşırsan `slots` sayısını azalt.
