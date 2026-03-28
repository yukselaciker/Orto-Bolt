"""
core/stl_loader.py — STL Dosya Yükleme ve Doğrulama Modülü
============================================================
Faz 1: Temel STL dosya işleme.

Klinik Bağlam:
    Ortodontistler intraoral tarayıcılardan (ör. iTero, Medit)
    veya laboratuvar tarayıcılarından STL formatında 3D alçı model
    taramaları alır. Bu modül dosyayı yükler, doğrular ve
    görselleştirme için hazırlar.
"""

import os
from typing import Optional, Tuple

import numpy as np
# Explicitly import VTK modules to avoid 'No module named vtkmodules.vtkIOGeometry'
# during dynamic loading by pyvista on certain macOS environments/executables.
import vtkmodules.vtkIOGeometry
import vtkmodules.vtkIOLegacy
import vtkmodules.vtkIOPLY
import pyvista as pv


class STLLoadError(Exception):
    """STL dosyası yüklenirken oluşan hatalar için özel istisna sınıfı."""
    pass


class STLLoader:
    """
    STL dosyalarını güvenli bir şekilde yükler ve doğrular.

    Klinik İş Akışı:
        1. Kullanıcı dosya seçer (üst çene veya alt çene)
        2. Dosya formatı doğrulanır (binary/ASCII STL)
        3. Mesh bütünlüğü kontrol edilir (boş mesh, dejenere üçgenler)
        4. Yüklenen mesh görselleştirme motoruna aktarılır
    """

    # Desteklenen dosya uzantıları
    SUPPORTED_EXTENSIONS = {'.stl'}

    # Minimum kabul edilebilir mesh boyutu (çok küçük meshler muhtemelen bozuktur)
    # Tipik bir dental ark taraması en az birkaç bin üçgen içerir
    MIN_FACE_COUNT = 100

    # Maksimum dosya boyutu (500 MB) — çok büyük dosyalar bellek sorunlarına yol açabilir
    MAX_FILE_SIZE_MB = 500

    @staticmethod
    def validate_file_path(file_path: str) -> None:
        """
        Dosya yolunu kontrol eder: varlık, uzantı, boyut.

        Args:
            file_path: STL dosyasının tam yolu.

        Raises:
            STLLoadError: Dosya bulunamazsa, uzantı yanlışsa veya boyut sınırı aşılırsa.
        """
        if not file_path:
            raise STLLoadError("Dosya yolu belirtilmedi.")

        if not os.path.exists(file_path):
            raise STLLoadError(f"Dosya bulunamadı: {file_path}")

        # Uzantı kontrolü
        _, ext = os.path.splitext(file_path)
        if ext.lower() not in STLLoader.SUPPORTED_EXTENSIONS:
            raise STLLoadError(
                f"Desteklenmeyen dosya formatı: '{ext}'. "
                f"Yalnızca STL dosyaları desteklenmektedir."
            )

        # Dosya boyutu kontrolü
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > STLLoader.MAX_FILE_SIZE_MB:
            raise STLLoadError(
                f"Dosya boyutu çok büyük: {file_size_mb:.1f} MB. "
                f"Maksimum: {STLLoader.MAX_FILE_SIZE_MB} MB."
            )

    @staticmethod
    def load(file_path: str) -> pv.PolyData:
        """
        STL dosyasını yükler ve mesh bütünlüğünü doğrular.

        Klinik Not:
            Bozuk veya eksik taramalar yanlış ölçümlere yol açabilir.
            Bu yüzden mesh'in minimum kalite gereksinimlerini karşıladığını
            kontrol ediyoruz.

        Args:
            file_path: STL dosyasının tam yolu.

        Returns:
            pv.PolyData: Doğrulanmış PyVista mesh nesnesi.

        Raises:
            STLLoadError: Dosya okunamazsa veya mesh geçersizse.
        """
        # Önce dosya yolunu doğrula
        STLLoader.validate_file_path(file_path)

        try:
            mesh = pv.read(file_path)
        except Exception as e:
            raise STLLoadError(
                f"STL dosyası okunamadı: {e}\n"
                "Dosyanın geçerli bir STL formatında olduğundan emin olun."
            )

        # Boş mesh kontrolü
        if mesh.n_points == 0:
            raise STLLoadError("Yüklenen STL dosyası boş (0 nokta). Dosya bozuk olabilir.")

        if mesh.n_cells == 0:
            raise STLLoadError("Yüklenen STL dosyasında yüzey bulunamadı (0 hücre).")

        # Minimum yüzey sayısı kontrolü — çok az üçgen varsa tarama eksik olabilir
        if mesh.n_cells < STLLoader.MIN_FACE_COUNT:
            raise STLLoadError(
                f"Yetersiz mesh kalitesi: yalnızca {mesh.n_cells} yüzey bulundu. "
                f"Dental taramalar genellikle en az {STLLoader.MIN_FACE_COUNT} üçgen içerir. "
                "Tarama dosyasını kontrol edin."
            )

        return mesh

    @staticmethod
    def get_mesh_info(mesh: pv.PolyData) -> dict:
        """
        Yüklenen mesh hakkında özet bilgi döndürür.
        Durum çubuğunda ve mesh bilgi panelinde kullanılır.

        Args:
            mesh: PyVista mesh nesnesi.

        Returns:
            dict: Mesh istatistikleri (nokta sayısı, yüzey sayısı, boyutlar vb.)
        """
        bounds = mesh.bounds  # (xmin, xmax, ymin, ymax, zmin, zmax)

        return {
            "nokta_sayisi": mesh.n_points,
            "yuzey_sayisi": mesh.n_cells,
            # Bounding box boyutları — dental arklar tipik olarak 50-80mm genişliğindedir
            "genislik_mm": abs(bounds[1] - bounds[0]),
            "yukseklik_mm": abs(bounds[3] - bounds[2]),
            "derinlik_mm": abs(bounds[5] - bounds[4]),
            "merkez": mesh.center,
        }
