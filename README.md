# AutoKeyboard 腳本精靈

這是一個 Windows 桌面工具，可建立多個自動按鍵腳本，並為每個腳本設定不同快捷鍵。按一次快捷鍵啟動，再按一次會立即停止對應腳本。

## 使用方式

1. 執行 `run.bat`，或在此資料夾執行：

   ```powershell
   python autokeyboard.py
   ```

2. 在左側新增或選擇腳本。
3. 設定腳本名稱、快捷鍵，例如 `F8`、`CTRL+F9`、`ALT+SHIFT+P`。
4. 在「按鍵步驟」設定按鍵指令或延遲。
5. 按鍵欄旁的「錄製」可直接按下鍵盤按鍵帶入。
6. 腳本名稱、快捷鍵、循環設定與目前選取的步驟編輯都會自動儲存；設定完成後即可使用快捷鍵啟動或停止。

腳本設定會存到 `%LOCALAPPDATA%\AutoKeyboard\scripts.json`。

如果是從舊版升級，第一次啟動時會自動把舊版安裝目錄內的 `scripts.json` 複製到新的使用者設定目錄。

## 更新程式

主畫面右上角的「檢查更新」會讀取 `ha850411/autokeyboard` 上的 `installer.iss` 版本，發現新版後下載 `installer/AutoKeyboard_Setup.exe`，並啟動安裝程式。

新版步驟採用羅技巨集那種動作式流程：

1. `X` `按下按鍵`
2. `延遲` `1000` ms
3. `X` `放開按鍵`

上面代表按住 `X` 一秒。若要再等待半秒，就再插入一個 `延遲` `500` ms。

同一個「按下按鍵 / 放開按鍵」動作也可以放多個按鍵，用逗號分隔：

1. `X, SPACE` `按下按鍵`
2. `延遲` `1000` ms
3. `X, SPACE` `放開按鍵`

這會同時按住 `X` 和 `SPACE` 一秒。

`延遲` 期間如果有尚未「放開按鍵」的按鍵，程式會持續補送那些按鍵的「按下按鍵」，讓一般視窗更接近實際按住鍵盤的效果。

介面上 `延遲` 是獨立動作設定：選 `延遲` 時只會顯示延遲毫秒欄位；按鍵指令會自動產生「按下按鍵」與「放開按鍵」。選取既有步驟後修改表單會自動更新該步驟，不需要另外按更新按鈕。

目前新增步驟的動作選項有兩種：

- `按鍵指令`：新增時會自動產生「按下按鍵」和「放開按鍵」一組底層指令。
- `延遲`：新增一個獨立延遲指令。

新增步驟會插入在目前選取步驟的下一格；沒有選取步驟時才會加到最下方。步驟清單支援多選。選取多個指令後可按「複製指令」批次複製，也可按鍵盤 `Delete` 快速刪除選取指令。

快捷鍵欄與按鍵欄都支援聚焦即錄製：游標在輸入框內時直接按下鍵盤，就會自動帶入對應按鍵，不會再彈出錄製視窗。

快捷鍵會以實體鍵為準，例如 `Shift+1` 會錄成 `SHIFT+1`，不會錄成 `!` 或其他導覽鍵。同一組快捷鍵只能指定給一個腳本，重複設定會被拒絕。

## 按鍵格式

可輸入一般按鍵與組合鍵，例如：

- `A`
- `SPACE`
- `ENTER`
- `LEFT`
- `F8`
- `CTRL+C`
- `SHIFT+A`
- `SHIFT`
- `PLUS`

如果要對系統管理員權限的程式送出按鍵，請用系統管理員身分啟動此工具。

## 測試

測謊偵測的 regression test 可執行：

```powershell
python -m unittest discover -s tests
```

目前測試包含按鍵解析、腳本序列化、設定檔讀寫、測謊偵測設定、腳本執行器與測謊圖片情境。

測試情境圖片可放在：

- `tests/fixtures/lie_detection_false_positives/`：不應該被偵測為測謊的截圖。
- `tests/fixtures/lie_detection_true_positives/`：必須被偵測為測謊的截圖。

測試會掃描這兩個資料夾與其子資料夾內的 `.png`、`.jpg`、`.jpeg`、`.bmp`、`.webp`。

## 打包 exe

已安裝 PyInstaller 後可執行：

```powershell
python -m PyInstaller AutoKeyboard.spec --clean --noconfirm
```

輸出檔會在 `dist\AutoKeyboard\AutoKeyboard.exe`。

如果目標程式是用系統管理員權限執行，可另外打包需要系統管理員權限的版本：

```powershell
python -m PyInstaller --noconsole --onefile --uac-admin --name AutoKeyboard_admin autokeyboard.py
```

輸出檔會在 `dist\AutoKeyboard_admin.exe`。

## 遊戲內沒有反應

請先用記事本測試腳本是否能正常輸出按鍵。如果記事本有效、遊戲內無效，常見原因是遊戲使用防作弊、Raw Input、DirectInput，或刻意忽略 Windows 模擬按鍵。這種限制無法用一般桌面程式保證送入，也不建議繞過遊戲防作弊機制。

如果遊戲是用系統管理員權限啟動，請改用系統管理員權限啟動本工具，或使用 `AutoKeyboard_admin.exe`。
