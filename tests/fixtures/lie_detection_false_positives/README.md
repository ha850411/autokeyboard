# Lie Detection False Positive Fixtures / 測謊偵測誤判情境

## 中文

當一般遊戲畫面或其他 app 畫面被錯誤偵測為測謊時，請把截圖放在這個資料夾。
子資料夾也會被掃描。

支援的圖片格式：`.png`、`.jpg`、`.jpeg`、`.bmp`、`.webp`。

執行測試：

```powershell
python -m unittest discover -s tests
```

如果這個資料夾中的任何圖片被偵測為測謊，測試就會失敗。

## English

Put screenshots here when a normal game or app screen is incorrectly detected as lie detection.
Subfolders are scanned too.

Supported file types: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp`.

Run:

```powershell
python -m unittest discover -s tests
```

The matcher test will fail if any image in this folder is detected.
