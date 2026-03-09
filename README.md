# music-cli

聚合音乐搜索 + 下载 CLI，支持酷狗、网易云、QQ 三平台，逐字歌词优先。

## 功能

- 并行搜索三个平台，2s 内返回结果
- 显示歌词精度（逐字 / 逐行），优先展示逐字版本
- 交互选择，下载**歌词 + 音频**到同一文件夹
- KRC（酷狗逐字）、YRC（网易云逐字）原格式保存
- 音频自动转 MP3（ffmpeg）

## 安装

```bash
pip install requests musicdl
brew install ffmpeg   # macOS，用于音频转码
```

## 使用

```bash
python music_search.py 素颜
python music_search.py "周杰伦 稻香" -n 10        # 每平台显示10条
python music_search.py 晴天 -p kg ne             # 只搜酷狗和网易云
python music_search.py 弱水三千 --no-audio        # 只下载歌词
```

搜索后输入编号选择，支持多选：

```
选择编号 (1-15，多个用逗号，回车取消): 1,3,5-7
```

## 输出结构

```
~/Music/lddc/
  素颜_许嵩、何曼婷/
    素颜_许嵩、何曼婷.krc     # KRC 逐字歌词
    素颜_许嵩、何曼婷.mp3     # 音频
  弱水三千_张晓棠、石头/
    弱水三千_张晓棠、石头.krc
    弱水三千_张晓棠、石头.mp3
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
