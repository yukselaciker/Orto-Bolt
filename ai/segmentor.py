"""
ai/segmentor.py — Diş Segmentasyon Motoru
============================================
Faz 3: CrossTooth / MeshSegNet modelini çalıştırarak
her noktaya diş etiketi atar.

Tasarım Kararı:
    İki mod desteklenir:
    1. PyTorch modeli varsa → GPU/CPU'da gerçek çıkarım
    2. Model yoksa → basit geometrik segmentasyon (fallback)

    Fallback mod, model ağırlıkları yüklenmeden de uygulamanın
    çalışmasını sağlar. Ortodontist sonuçları manuel düzeltebilir.

    FDI Etiket Haritası:
        Teeth3DS yarışması 0=gingiva, 1-16=dişler kullanır.
        Üst çene: 1→11, 2→12, ..., 8→18 (sağdan sola)
        Alt çene: 9→41, 10→42, ..., 16→48

        Bolton analizi yalnızca FDI 11-16, 21-26, 31-36, 41-46 kullanır.
"""

from typing import Dict, Optional, Tuple, List
from pathlib import Path
import numpy as np

# PyTorch opsiyonel — fallback mod varsa import hatası yutulur
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# ──────────────────────────────────────────────────
# FDI ETİKET HARİTASI
# ──────────────────────────────────────────────────

# Teeth3DS challenge'da sınıf indeksleri → FDI numaraları
# Üst çene (maxilla): sağ → sol
UPPER_CLASS_TO_FDI = {
    1: 11, 2: 12, 3: 13, 4: 14, 5: 15, 6: 16, 7: 17, 8: 18,
    9: 21, 10: 22, 11: 23, 12: 24, 13: 25, 14: 26, 15: 27, 16: 28,
}

# Alt çene (mandible): sağ → sol
LOWER_CLASS_TO_FDI = {
    1: 41, 2: 42, 3: 43, 4: 44, 5: 45, 6: 46, 7: 47, 8: 48,
    9: 31, 10: 32, 11: 33, 12: 34, 13: 35, 14: 36, 15: 37, 16: 38,
}

# Gingiva sınıf ID'si
GINGIVA_CLASS = 0

# Varsayılan ağırlık dosyası yolu
DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "weights" / "point_best_model.pth"


class ToothSegmentor:
    """
    Diş segmentasyon motoru.

    İki modda çalışır:
        1. AI modu: CrossTooth/MeshSegNet modeli ile gerçek çıkarım
        2. Geometrik mod: PCA + kümeleme ile basit segmentasyon (fallback)

    Kullanım:
        segmentor = ToothSegmentor()
        labels, fdi_map = segmentor.segment(features, jaw_type="maxillary")

    Attributes:
        model: PyTorch modeli (None ise geometrik mod kullanılır).
        device: Çıkarım cihazı ("cuda" veya "cpu").
        is_ai_mode: AI modeli yüklü mü?
    """

    def __init__(self, weights_path: Optional[str] = None):
        """
        Segmentor'u başlatır.

        Args:
            weights_path: Model ağırlık dosyası yolu.
                         None ise varsayılan konuma bakar.
                         Dosya bulunamazsa geometrik moda düşer.
        """
        self.model = None
        self.device = "cpu"
        self.is_ai_mode = False

        if TORCH_AVAILABLE:
            if torch.cuda.is_available():
                self.device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self.device = "mps"  # Apple Silicon GPU

        # Model yüklemeyi dene
        wp = Path(weights_path) if weights_path else DEFAULT_WEIGHTS_PATH
        if wp.exists() and TORCH_AVAILABLE:
            try:
                self._load_model(wp)
                self.is_ai_mode = True
            except Exception as e:
                print(f"⚠ Model yüklenemedi: {e}")
                print("  → Geometrik segmentasyon moduna geçiliyor.")

    def _load_model(self, weights_path: Path) -> None:
        """
        CrossTooth model ağırlıklarını yükler.

        Args:
            weights_path: .pth dosyasının yolu.
        """
        checkpoint = torch.load(
            weights_path,
            map_location=self.device,
            weights_only=False,
        )

        # CrossTooth modeli state_dict formatında kaydedilmiş olabilir
        if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
            state_dict = checkpoint["model_state_dict"]
        elif isinstance(checkpoint, dict) and "state_dict" in checkpoint:
            state_dict = checkpoint["state_dict"]
        else:
            state_dict = checkpoint

        # Not: Gerçek CrossTooth model mimarisi ayrıca tanımlanmalı.
        # Şimdilik sadece state_dict'i saklıyoruz.
        self._state_dict = state_dict
        print(f"✅ Model ağırlıkları yüklendi: {weights_path.name}")
        print(f"   Cihaz: {self.device}")

    def segment(
        self,
        features: np.ndarray,
        jaw_type: str = "maxillary",
        raw_points: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, Dict[int, np.ndarray]]:
        """
        Nokta bulutunu segmentlere ayırır.

        Args:
            features: (N, 6) [x,y,z,nx,ny,nz] normalize edilmiş girdi.
            jaw_type: "maxillary" veya "mandibular".
            raw_points: (N, 3) ham koordinatlar (mm, geometrik mod için).

        Returns:
            Tuple[labels, tooth_points]:
                - labels: (N,) her noktanın FDI etiketi (0=gingiva).
                - tooth_points: Dict[fdi → (M, 3) koordinat dizisi].
                  Her dişe ait noktaların mm koordinatları.
        """
        if self.is_ai_mode:
            return self._segment_ai(features, jaw_type, raw_points)
        else:
            return self._segment_geometric(features, jaw_type, raw_points)

    def _segment_ai(
        self,
        features: np.ndarray,
        jaw_type: str,
        raw_points: Optional[np.ndarray],
    ) -> Tuple[np.ndarray, Dict[int, np.ndarray]]:
        """
        AI modeli ile segmentasyon.
        Not: Tam CrossTooth mimarisi entegre edildiğinde burada çıkarım yapılacak.
        Şimdilik geometrik moda düşer.
        """
        # TODO: CrossTooth model mimarisini tanımla ve çıkarımı implemente et
        print("ℹ AI segmentasyon henüz tam entegre değil → geometrik mod kullanılıyor")
        return self._segment_geometric(features, jaw_type, raw_points)

    def _segment_geometric(
        self,
        features: np.ndarray,
        jaw_type: str,
        raw_points: Optional[np.ndarray],
    ) -> Tuple[np.ndarray, Dict[int, np.ndarray]]:
        """
        Geometrik segmentasyon v2 — Ark Eğrisi + Valley Tespiti.

        Neden çalışıyor:
            Eski versiyon X eksenini eşit dilimlere bölüyordu — dişlerin
            fiziksel sınırlarını görmezden geliyordu.
            Bu versiyon gerçek interproksimal boşlukları (vadileri) tespit eder.
        """
        from scipy.signal import find_peaks
        from scipy.ndimage import gaussian_filter1d
        from sklearn.decomposition import PCA

        points = raw_points if raw_points is not None else features[:, :3]
        n = len(points)
        labels = np.zeros(n, dtype=np.int32)

        # ── 1. Gingival noktaları at ──
        y_vals = points[:, 1]
        y_range = y_vals.max() - y_vals.min()
        if y_range < 1e-6:
            y_vals = points[:, 2]
            y_range = y_vals.max() - y_vals.min()

        if jaw_type == "maxillary":
            tooth_mask = y_vals > (y_vals.min() + 0.45 * y_range)
        else:
            tooth_mask = y_vals < (y_vals.max() - 0.45 * y_range)

        tooth_indices = np.where(tooth_mask)[0]
        if len(tooth_indices) < 60:
            tooth_indices = np.arange(n)

        tooth_pts = points[tooth_indices]

        # ── 2. Ark eksenini PCA ile bul ──
        centroid = tooth_pts.mean(axis=0)
        centered = tooth_pts - centroid
        pca = PCA(n_components=2)
        pca.fit(centered)
        arch_axis = pca.components_[0]

        # ── 3. 1D projeksiyon + yoğunluk histogramı ──
        proj = centered @ arch_axis

        n_bins = 400
        proj_min, proj_max = proj.min(), proj.max()
        hist, bin_edges = np.histogram(proj, bins=n_bins)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        smoothed = gaussian_filter1d(hist.astype(float), sigma=3.5)

        # ── 4. Vadi tespiti = interproksimal boşluklar ──
        inverted = smoothed.max() - smoothed
        peak_height_threshold = inverted.max() * 0.25

        valley_indices, _ = find_peaks(
            inverted,
            height=peak_height_threshold,
            distance=n_bins // 16,
        )

        if len(valley_indices) >= 5:
            heights = inverted[valley_indices]
            top5_idx = np.argsort(heights)[-5:]
            selected_valleys = np.sort(valley_indices[top5_idx])
        elif len(valley_indices) > 0:
            selected_valleys = np.sort(valley_indices)
        else:
            selected_valleys = np.array([int(n_bins * (i + 1) / 6) for i in range(5)])

        valley_projs = bin_centers[selected_valleys]

        # ── 5. Sınırları oluştur ──
        boundaries = np.concatenate([
            [proj_min - 0.1],
            sorted(valley_projs),
            [proj_max + 0.1],
        ])

        # ── 6. FDI ataması ──
        arch_goes_right = arch_axis[0] >= 0

        if jaw_type == "maxillary":
            fdi_left_to_right = [26, 25, 24, 23, 22, 21, 11, 12, 13, 14, 15, 16]
        else:
            fdi_left_to_right = [36, 35, 34, 33, 32, 31, 41, 42, 43, 44, 45, 46]

        fdi_order = list(fdi_left_to_right) if arch_goes_right else list(reversed(fdi_left_to_right))

        n_segments = len(boundaries) - 1
        if n_segments != 6:
            mid = len(fdi_order) // 2
            half = n_segments // 2
            fdi_order = fdi_order[mid - half: mid - half + n_segments]

        tooth_point_groups: Dict[int, np.ndarray] = {}

        for seg_i, fdi in enumerate(fdi_order[:n_segments]):
            lo = boundaries[seg_i]
            hi = boundaries[seg_i + 1]
            seg_mask = (proj >= lo) & (proj < hi)
            seg_local_idx = np.where(seg_mask)[0]
            if len(seg_local_idx) == 0:
                continue
            global_idx = tooth_indices[seg_local_idx]
            labels[global_idx] = fdi
            tooth_point_groups[fdi] = points[global_idx]

        return labels, tooth_point_groups

    @property
    def mode_description(self) -> str:
        """Aktif modun açıklamasını döndürür."""
        if self.is_ai_mode:
            return f"🤖 AI Segmentasyon ({self.device})"
        else:
            return "📐 Geometrik Segmentasyon (fallback)"
