# 🦷 AI-Powered Dental Bolton Analyzer (STL)

> Ortodontistler için yüzey tarama modellerini kullanarak **Bolton Analizini** otomatikleştiren özel 3D dental yazılımı.

---

## 📌 Proje Genel Bakışı

**Bolton Analizi**, maksiller ve mandibüler dişler arasındaki orantısallığı belirlemek için kullanılan temel bir ortodontik tanı aracıdır. Bu uygulama, fiziksel alçı modeller üzerindeki manuel kumpas ölçümlerinin yerini alacak dijital bir iş akışı sunar.

---

## 🛠 Temel Özellikler

### 1. 3D Mesh Görselleştirme
- **STL Yükleme:** Binary ve ASCII STL dosyalarını (Üst ve Alt ark) destekler.
- **İnteraktif Görüntüleyici:** `PyVista` veya `Open3D` kullanarak 3D orbit, zoom ve pan.
- **Çift Görüntü Portu:** Maksilla ve Mandibula'nın senkronize veya bağımsız görüntülenmesi.

### 2. Analiz Modları
- **Yarı-Otomatik Mod:**
  - 3D mesh üzerinde rehberli "Nokta Seçimi" (Point Picking).
  - Kullanıcı her diş için **Mezial** ve **Distal** temas noktalarını tıklar.
  - Gerçek zamanlı Öklidyen mesafe hesaplaması.
- **Tam AI Otomasyonu *(Planlanıyor)*:**
  - Derin Öğrenme (ör. MeshSegNet) kullanarak otomatik diş segmentasyonu.
  - Maksimum meziodisal çaplar için otomatik landmark tespiti.

### 3. Ortodontik Hesaplamalar

**Anterior Oran (6 diş):**

$$Ratio_{Ant} = \frac{\sum \text{Mandibular } 3\text{-}3}{\sum \text{Maxillary } 3\text{-}3} \times 100 \quad (\text{Hedef: } 77.2\%)$$

**Genel Oran (12 diş):**

$$Ratio_{Total} = \frac{\sum \text{Mandibular } 6\text{-}6}{\sum \text{Maxillary } 6\text{-}6} \times 100 \quad (\text{Hedef: } 91.3\%)$$

- **Uyumsuzluk Analizi:** Milimetre cinsinden diş boyutu fazlasının hesaplanması.

---

## 🏗 Teknik Yığın

| Bileşen | Teknoloji |
|---|---|
| Dil | Python 3.10+ |
| 3D Motor | `PyVista` / `VTK` |
| UI Çerçevesi | `PyQt6` / `PySide6` |
| Veri İşleme | `NumPy`, `Pandas` |
| Raporlama | `ReportLab` (PDF) |

---

## 🚀 Yol Haritası

### Faz 1 — Ortam Kurulumu
- [ ] 3D render penceresi ile temel UI oluştur.
- [ ] STL dosyası içe aktarma işlevini ekle.

### Faz 2 — Ölçüm Araçları
- [ ] Nokta seçimi (point-picking) etkileşim mantığını geliştir.
- [ ] 12+12 dişin genişliklerini depolamak için liste/tablo oluştur.

### Faz 3 — Otomasyon
- [ ] Otomatik segmentasyon için AI modellerini entegre et.
- [ ] En belirgin meziodisal noktalara "Otomatik Yakalama" özelliği ekle.

### Faz 4 — Dışa Aktarma & Klinik Raporlar
- [ ] Hasta kimliği, diş ölçümleri ve Bolton yüzdelerini içeren PDF özetleri oluştur.

---

## 💻 AI Geliştirici Ajanları için Talimatlar

> Bu README'yi bir plan olarak kullanan ajan: **PyVista** ve **PyQt6** kullanan bir Python scripti oluşturmaya başla. Script; bir STL dosyası yükleyicisi olan bir pencere açmalı ve 3D modeli görüntülemelidir. Yüklendikten sonra, kullanıcının mesh üzerinde iki nokta tıklamasına izin ver ve aralarındaki mesafeyi konsola yazdır.

### Başlangıç Kod İskeleti

```python
import sys
import pyvista as pv
from pyvistaqt import BackgroundPlotter
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QFileDialog, QVBoxLayout, QWidget

class BoltonAnalyzer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bolton Analyzer - STL Viewer")
        self.picked_points = []
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        layout = QVBoxLayout()
        btn_load = QPushButton("STL Dosyası Yükle")
        btn_load.clicked.connect(self.load_stl)
        layout.addWidget(btn_load)
        self.plotter = BackgroundPlotter()
        central.setLayout(layout)
        self.setCentralWidget(central)

    def load_stl(self):
        path, _ = QFileDialog.getOpenFileName(self, "STL Seç", "", "STL Files (*.stl)")
        if path:
            mesh = pv.read(path)
            self.plotter.add_mesh(mesh, color="ivory")
            self.plotter.enable_point_picking(
                callback=self.on_point_picked,
                use_mesh=True,
                show_message=True
            )

    def on_point_picked(self, point):
        self.picked_points.append(point)
        print(f"Nokta seçildi: {point}")
        if len(self.picked_points) == 2:
            p1, p2 = self.picked_points
            dist = ((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2 + (p2[2]-p1[2])**2) ** 0.5
            print(f"Meziodisal Genişlik: {dist:.2f} mm")
            self.picked_points.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BoltonAnalyzer()
    window.show()
    sys.exit(app.exec())
```

### Gereksinimler

```bash
pip install pyvista pyvistaqt PyQt6 numpy pandas reportlab
```

---

## 📁 Proje Yapısı

```
bolton-analyzer/
├── main.py                 # Uygulama giriş noktası
├── scripts/                # Çalıştırma ve sağlık kontrol yardımcıları
│   ├── dev_run.py          # Geliştirme autoreload döngüsü
│   ├── qt_healthcheck.py   # Qt başlangıç sağlık kontrolü
│   └── repair_venv.py      # Taşınmış sanal ortam yol onarımı
├── tests/
│   ├── fixtures/           # Manuel test fixture dosyaları
│   └── manual/             # Tek seferlik/etkileşimli debug testleri
├── ui/
│   ├── main_window.py      # Ana pencere bileşenleri
│   └── viewer.py           # 3D mesh görüntüleyici
├── core/
│   ├── stl_loader.py       # STL dosya işleme
│   ├── measurements.py     # Mesafe ve oran hesaplamaları
│   └── bolton_logic.py     # Bolton formülleri
├── ai/
│   └── segmentation.py     # AI segmentasyon modülü (Faz 3)
├── reports/
│   └── pdf_generator.py    # ReportLab PDF raporu
├── data/
│   └── patients/           # Hasta STL dosyaları
├── requirements.txt
└── README.md
```

---

## 📊 Bolton Referans Değerleri

| Analiz Türü | Hedef Oran | Kabul Edilebilir Aralık |
|---|---|---|
| Anterior (3-3) | %77.2 | %74.5 – %80.4 |
| Genel (6-6) | %91.3 | %87.5 – %94.8 |

> **Not:** Klinik değerlendirme, hesaplanan değerler referans aralığın dışına çıktığında disk büyüklüğü (IPR veya protez genişletme) için tedavi planlamasını rehberler.

---

## 📄 Lisans

Bu proje ortodontik araştırma ve klinik kullanım amacıyla geliştirilmektedir.

---

*🏥 Ortodontik Araştırma ve Klinik Mükemmellik için Geliştirilmiştir.*
