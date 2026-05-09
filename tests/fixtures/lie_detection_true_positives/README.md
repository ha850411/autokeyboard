# Lie Detection True Positive Fixtures / 測謊偵測命中情境

## 中文

當畫面應該被偵測為測謊時，請把截圖放在這個資料夾。
子資料夾也會被掃描。

支援的圖片格式：`.png`、`.jpg`、`.jpeg`、`.bmp`、`.webp`。

執行測試：

```powershell
python -m unittest discover -s tests
```

如果這個資料夾中的任何圖片沒有被偵測為測謊，測試就會失敗。

## English

Put screenshots here when a screen should be detected as lie detection.
Subfolders are scanned too.

Supported file types: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`.

Run:

```powershell
python -m unittest discover -s tests
```

The matcher test will fail if any image in this folder is not detected.
