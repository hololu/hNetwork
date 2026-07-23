# hnetwork 🌐

**Çoklu arayüz + çoklu VLAN destekli, modern ağ tarayıcı** (eski `my_network_scanner` projesinin sıfırdan yeniden yazılmış hâli).

## Özellikler
- ✅ **Çoklu arayüz taraması** — `eth0`, `wlan0`, `docker0` ... hepsini tek seferde tarayın
- ✅ **Çoklu VLAN taraması** — `eth0.10`, `eth0.20` (802.1q sub-interface) otomatik algılanır
- ✅ Hedef olarak **arayüz adı / VLAN / CIDR / IP aralığı** karışık kullanılabilir
- ✅ **Gerçek tarama, root/nmap gerektirmez** — saf-Python motoru (ping sweep + TCP socket + ARP tablosu)
  - root + nmap varsa otomatik olarak ARP/nmap motoruna geçer (sessiz cihazları da yakalar)
- ✅ MAC → üretici (OUI) tespiti — tam **IEEE OUI veritabanı** (39.8k kayıt) + `mac-vendor.txt` birleşimi
- ✅ Hostname çözümleme, cihaz tipi tespiti + güven skoru
- ✅ Modern web arayüzü:
  - **Açık / Koyu tema** geçişi (tercih hatırlanır)
  - **Sol menü aç/kapa** (☰ butonu, tercih hatırlanır)
  - Canlı ilerleme çubuğu (gerçek yüzde)
  - Cihaz **türü pill'lerine tıklayarak filtreleme**
  - **Sayfalama** — sayfada kaç kayıt görüneceği seçilebilir (10/25/50/100/Tümü)
  - Arama kutusu (IP, host, vendor, tip)
  - **TXT / CSV / JSON export**
  - **Periyodik otomatik tarama** zamanlayıcısı (1dk–1sa aralık)
- ✅ CLI aracı (`hnetwork eth0 eth0.10 10.0.0.0/24`)

## Kurulum
```bash
cd calismalar/hnetwork
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
# veya: pip install -e .
```

## Çalıştırma
```bash
# Web arayüzü (http://localhost:5883)
python -m hnetwork.web

# CLI
hnetwork --list-interfaces
hnetwork eth0 eth0.10 192.168.1.0/24 --profile full
hnetwork --update-oui mac-vendor.txt   # MAC üretici DB'sini dosyadan güncelle
hnetwork --update-oui                  # IEEE'den online güncelle
```

> **root + nmap** varsa uygulama daha derin tarama yapar (ARP ile sessiz cihazlar, servis/OS parmak izi).
> Aksi hâlde güvenli şekilde **saf-Python gerçek tarama** yapar (ping + TCP socket + ARP tablosu). Demo/simülasyon modu yoktur.

## Web Arayüzü Kılavuzu
- **☰** (sol üst) — sol menüyü gizle/göster
- **☀/🌙** (sağ üst) — açık/koyu tema
- **Arayüzler & VLAN** — arayüz/VLAN kutuları, "Tümünü Seç / Temizle / Yerel ağlar" butonları
- **Tarama Seçenekleri** — profil (basic/full), çevrimdışı dahil, "Taramayı Başlat"
- **Periyodik Otomatik Tarama** — etkin + aralık seç → arka planda tekrarlanan tarama
- **Cihazlar** — sayfa boyutu seçici, TXT/CSV/JSON export, tür pill filtresi, arama
- **Özet** — toplam/çevrimiçi/hedet/tip sayıları + tür dağılımı (tıklanabilir)

## Mimari
```
hnetwork/
├── config.py      # kalıcı ayarlar (JSON)
├── interfaces.py  # arayüz / VLAN / hedef çözümleme
├── oui.py         # MAC üretici veritabanı + IEEE/mac-vendor.txt import
├── detection.py   # cihaz tipi tespiti
├── scanner.py     # ana tarama motoru (çoklu hedef, gerçek tarama)
├── web.py         # Flask uygulaması + REST API + periyodik scheduler
├── cli.py         # komut satırı aracı
└── templates/     # modern web arayüzü (tema + sayfalama + export)
```

## REST API
| Endpoint | Açıklama |
|----------|----------|
| `GET /api/interfaces` | Mevcut arayüzler |
| `GET /api/vlans` | VLAN sub-interface'leri |
| `POST /api/scan` | Tarama başlat (`{targets, profile, include_offline}`) |
| `GET /api/progress` | Canlı ilerleme (gerçek yüzde) |
| `POST /api/stop` | Taramayı durdur |
| `GET /api/results` | Bulunan cihazlar (tümü) |
| `GET /api/devices` | Bulunan cihazlar (liste) |
| `GET /api/export/<fmt>` | Export: `txt` / `csv` / `json` (dosya indirir) |
| `GET/POST /api/schedule` | Periyodik tarama durumu/ayarı |

## Uzak Depoya Gönderme (push)
Proje yerel `~/calismalar/hnetwork` git deposudur. Uzak bir depoya göndermek için:
```bash
git remote add origin <repo-url>   # ilk kez
git branch -M main
git push -u origin main
```
Yedeği diske almak için (runtime veritabanı hariç):
```bash
tar --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    -czf ~/hnetwork_backup.tar.gz -C ~ calismalar/hnetwork
```
