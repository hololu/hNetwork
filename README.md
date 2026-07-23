# hnetwork 🌐

**Çoklu arayüz + çoklu VLAN destekli, modern ağ tarayıcı** (eski `my_network_scanner` projesinin sıfırdan yeniden yazılmış hâli).

## Özellikler
- ✅ **Çoklu arayüz taraması** — `eth0`, `wlan0`, `docker0` ... hepsini tek seferde tarayın
- ✅ **Çoklu VLAN taraması** — `eth0.10`, `eth0.20` (802.1q sub-interface) otomatik algılanır
- ✅ Hedef olarak **arayüz adı / VLAN / CIDR / IP aralığı** karışık kullanılabilir
- ✅ ARP + ping keşfi, TCP port taraması (basic / full profil)
- ✅ MAC → üretici (OUI) tespiti, hostname çözümleme
- ✅ Hostname / vendor / port kurallarıyla cihaz tipi tespiti + güven skoru
- ✅ Modern web arayüzü (koyu tema, canlı ilerleme, filtreleme)
- ✅ **Demo modu**: root/nmap olmadan arayüzü test etmek için simüle cihazlar
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
hnetwork --demo            # simülasyon
hnetwork --update-oui mac-vendor.txt   # MAC üretici DB'sini dosyadan güncelle
hnetwork --update-oui                  # IEEE'den online güncelle
```

> Gerçek tarama (ARP/port) için **root** yetkisi ve **nmap** gereklidir.
> Aksi hâlde uygulama otomatik olarak demo/simülasyon moduna geçer.

## Mimari
```
hnetwork/
├── config.py      # kalıcı ayarlar (JSON)
├── interfaces.py  # arayüz / VLAN / hedef çözümleme
├── oui.py         # MAC üretici veritabanı + cache
├── detection.py   # cihaz tipi tespiti
├── scanner.py     # ana tarama motoru (çoklu hedef + demo)
├── web.py         # Flask uygulaması + REST API
├── cli.py         # komut satırı aracı
└── templates/     # modern web arayüzü
```

## REST API
| Endpoint | Açıklama |
|----------|----------|
| `GET /api/interfaces` | Mevcut arayüzler |
| `GET /api/vlans` | VLAN sub-interface'leri |
| `POST /api/scan` | Tarama başlat (`{targets, profile, demo}`)
| `GET /api/progress` | Canlı ilerleme |
| `POST /api/stop` | Taramayı durdur |
| `GET /api/devices` | Bulunan cihazlar |
