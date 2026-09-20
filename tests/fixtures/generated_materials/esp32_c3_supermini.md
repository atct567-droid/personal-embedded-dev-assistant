# ESP32-C3 SuperMini 使用与排障（合成测试摘要）

## 下载模式和复位

电脑无法识别下载串口时，可以按住 BOOT 上电，或按住 BOOT、按下并释放 RESET，再释放 BOOT，使芯片进入下载模式。程序上传成功后，通常还需要按一次 RESET 才会执行新程序。

## USB 串口

如果 Arduino 串口监视器没有输出，需要检查工具栏中的 USB CDC On Boot 是否设置为 Enabled。示例程序使用 115200 波特率进行串口初始化。

## Wi-Fi 和 BLE 示例

Wi-Fi 示例调用 WiFi.begin 后循环等待 WL_CONNECTED，并周期性打印连接状态。BLE 示例创建服务和特征，特征具备 READ 与 WRITE 属性，在写入回调中读取新值并打印。
