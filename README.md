# music-cli

聚合音乐搜索 + 下载 CLI，支持酷狗、网易云、QQ 三平台，逐字歌词优先。

## 功能

- 默认快捷下载：一条命令直接下载酷狗第一条，无需交互
- `-n` 列表模式：并行搜索三平台，显示编号列表供选择
- 显示歌词精度（逐字 / 逐行）
- KRC（酷狗逐字）、YRC（网易云逐字）原格式保存
- 音频自动转 MP3（ffmpeg）

## 安装

```bash
pip install requests musicdl
brew install ffmpeg   # macOS，用于音频转码
```

## 使用

```bash
# 默认：快捷下载酷狗第一条，仅音频
python music_search.py 稻香

# 带歌词
python music_search.py 稻香 --lrc

# 列表模式：每平台返回5条，交互选择
python music_search.py 稻香 -n 5

# 限定平台
python music_search.py 稻香 -n 5 -p kg ne
python music_search.py 稻香 -p ne          # 快捷模式 + 指定平台

# 自定义保存目录
python music_search.py 稻香 -o ~/Downloads
```

列表模式支持多选：

```
选择编号 (1-15，多个用逗号，回车取消): 1,3,5-7
```

## 参数

| 参数 | 说明 |
|------|------|
| `-n <数量>` | 每平台返回条数，指定后进入列表选择模式 |
| `-p kg ne qq` | 限定搜索平台（kg酷狗 ne网易云 qq） |
| `--lrc` | 同时下载歌词（默认只下音频） |
| `-o <目录>` | 自定义保存目录（默认 ~/Music/lddc） |

## 输出结构

```
~/Music/lddc/
  稻香_周杰伦/
    稻香_周杰伦.mp3
  素颜_许嵩、何曼婷/
    素颜_许嵩、何曼婷.krc     # --lrc 时保存
    素颜_许嵩、何曼婷.mp3
```

## 歌词格式

| 格式 | 平台 | 精度 | 示例 |
|------|------|------|------|
| KRC  | 酷狗 | 逐字 | `[0,5539]<0,791,0>弱<791,791,0>水` |
| YRC  | 网易云 | 逐字 | `[16140,5290](16140,290,0)太` |
| LRC  | 通用 | 逐行 | `[01:22.23]弱水三千` |

## 文件说明

| 文件 | 说明 |
|------|------|
| `music_search.py` | 主 CLI |
| `audio_dl.py` | 子进程音频下载（被主程序调用） |
| `musicdl_patch.py` | monkey-patch musicdl，升级为逐字歌词 + 加速 |

## 参考项目

- [LDDC](https://github.com/chenmozhijin/LDDC) — 歌词下载器，KRC 解密算法来源
- [CharlesPikachu/musicdl](https://github.com/CharlesPikachu/musicdl) — 多平台音频下载库
- [musicdl_patch](musicdl_patch.py) — 本项目对 musicdl 的扩展，实现 KRC/YRC 逐字升级

## 依赖

- Python 3.10+
- `requests`
- `musicdl`
- `ffmpeg`（系统依赖，用于音频转码）
