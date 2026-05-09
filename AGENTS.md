# Codex Agent Instructions / Codex Agent 指示

## 必要驗證

每次修改程式碼後，結束前都必須執行測謊偵測 regression tests：

```powershell
python -m unittest discover -s tests
```

如果無法執行測試，必須在最終回覆中清楚說明原因。

## 測謊偵測情境圖片

誤判截圖請放在：

```text
tests/fixtures/lie_detection_false_positives/
```

這裡的任何圖片都不能被偵測為測謊。

必須通過偵測的截圖請放在：

```text
tests/fixtures/lie_detection_true_positives/
```

這裡的任何圖片都必須被偵測為測謊。

測試會掃描這兩個資料夾與其子資料夾內支援的圖片格式。

修改測謊偵測邏輯時，必須同時顧到兩邊：

- 真正的測謊模板仍然要能被偵測到。
- 已知的誤判截圖不能被偵測到。
- 已知的真實測謊截圖必須被偵測到。

## Required Verification

Every time you modify program code, run the lie detection regression tests before finishing:

```powershell
python -m unittest discover -s tests
```

If the test cannot be run, report the reason clearly in the final response.

## Lie Detection False Positives

False-positive screenshots belong in:

```text
tests/fixtures/lie_detection_false_positives/
```

Any image there must not be detected as lie detection.

True-positive screenshots belong in:

```text
tests/fixtures/lie_detection_true_positives/
```

Any image there must be detected as lie detection.

The test suite scans supported images in both folders and their subfolders.

When changing lie detection logic, keep both sides covered:

- The real lie detection template should still be detected.
- Known false-positive screenshots should not be detected.
- Known true-positive screenshots should be detected.
