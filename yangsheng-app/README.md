# 养生馆预约管理 H5 应用

手机端优先的网页应用，顾客扫码/点链接即可预约，店员可管理预约、开单收银、看营收统计、维护服务项目。

- **后端**: Python FastAPI + SQLite(单文件数据库，无需装数据库服务)
- **前端**: 纯 HTML/CSS/JS 单页，微信浏览器内可直接打开
- **部署**: Dockerfile + docker-compose，一条命令启动

## 功能一览

**顾客端(无需登录)**
- 服务列表:按分类展示项目与价格，一键预约
- 预约流程:选项目 → 选日期(未来 7 天) → 选时间(10:00–21:00 整点) → 填姓名+手机号 → 生成预约单号
- 我的预约:凭手机号查询，可取消"待到店"的预约

**店员端(密码登录)**
- 预约管理:按日期查看，可标记 已到店 / 已完成 / 已取消
- 快速开单:多选项目自动计价，现金/微信/支付宝，散客也能开单
- 营收统计:今日 / 本周 / 本月营收与订单数，本月项目销量排行
- 项目管理:新增 / 改价 / 改分类 / 上架下架

## 初始服务项目(8 个)

| # | 项目 | 价格 | 分类 |
|---|------|------|------|
| 1 | 面部护肤 | 58 元 | 面部护理 |
| 2 | 经典头疗 | 58 元 | 头部 |
| 3 | 肾部保养 | 68 元 | 身体调理 |
| 4 | 清肠排毒 | 68 元 | 身体调理 |
| 5 | 背部疏通 | 78 元 | 身体调理 |
| 6 | 腿部疏通 | 88 元 | 身体调理 |
| 7 | 调理腰腿 | 118 元 | 身体调理 |
| 8 | 背+胃+腿 | 198 元 | 优惠套餐 |

首次启动时自动写入数据库，之后可在"店员端 → 项目管理"里改价/增删。

## 快速部署(Docker，一条命令)

```bash
# 1. 进目录
cd yangsheng-app

# 2. ⚠️ 先改店员密码(默认 888888)
#    打开 docker-compose.yml，把 STAFF_PASSWORD=888888 改成你自己的密码

# 3. 启动
docker compose up -d

# 4. 打开浏览器访问
#    http://服务器IP:8000
```

数据保存在 `./data/app.db`，删容器重建不丢数据。查看日志: `docker compose logs -f`；停止: `docker compose down`。

## 本地运行(无 Docker)

```bash
cd yangsheng-app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 启动(默认端口 8000，默认店员密码 888888)
STAFF_PASSWORD=你的密码 python -m backend.app
# 或指定端口: PORT=9000 STAFF_PASSWORD=你的密码 python -m backend.app
```

浏览器打开 http://127.0.0.1:8000 即可。

## 修改店员密码

密码通过环境变量 `STAFF_PASSWORD` 设置，修改后重启生效:

- Docker: 改 `docker-compose.yml` 中的 `STAFF_PASSWORD`，然后 `docker compose up -d` 重建
- 本地: 启动命令前加 `STAFF_PASSWORD=新密码`

## 上云(二选一，小白可照做)

### 方案 A:Sealos(推荐，有免费额度，国内访问快)

1. 注册登录 [sealos.cloud](https://sealos.cloud)，进入「应用管理」→「新建应用」
2. 镜像名填 `python:3.11-slim`，或把本项目推到 GitHub 后用「从源码构建」(Dockerfile 已备好)
3. 如用源码构建:仓库选本项目，构建方式选 Dockerfile
4. 环境变量加一条: `STAFF_PASSWORD=你的店员密码`(务必修改默认的 888888)
5. 容器端口填 `8000`，开启「外网访问」(会分配一个公网域名)
6. 数据持久化:挂载 `容器的 /app/data` 到平台提供的存储卷(否则重建容器会丢预约/订单数据)
7. 点「部署」，拿到公网域名 → 生成二维码贴店里，顾客扫码即用

### 方案 B:Railway(国外平台，部署极简)

1. 把本项目推到 GitHub
2. 注册登录 [railway.app](https://railway.app) → New Project → Deploy from GitHub repo，选本仓库
3. Railway 会自动识别 Dockerfile 并构建；Variables 里加 `STAFF_PASSWORD=你的店员密码` 和 `PORT=8000`
4. Settings → Networking → Generate Domain，拿到公网域名
5. 注意:Railway 免费档重启后本地文件会丢，如需长期保留数据，请挂载 Volume 到 `/app/data`

> 两种方案都不需要备案即可先跑起来；若要绑定自己的域名 + 微信内稳定访问，Sealos 更合适。

## 接口速览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/services | 服务列表(上架) |
| GET | /api/meta | 可约日期(7天)+时间段 |
| POST | /api/bookings | 创建预约 |
| GET | /api/bookings?phone= | 查我的预约 |
| POST | /api/bookings/{id}/cancel?phone= | 取消预约 |
| POST | /api/staff/login | 店员登录(返回 token) |
| GET | /api/staff/bookings?d= | 按日期查预约 |
| POST | /api/staff/bookings/{id}/status | 改预约状态 |
| POST | /api/staff/orders | 快速开单 |
| GET | /api/staff/orders?d= | 按日期查订单 |
| GET | /api/staff/stats | 营收统计+销量排行 |
| GET/POST | /api/staff/services | 项目列表/新增 |
| PUT | /api/staff/services/{id} | 编辑项目(含改价/上下架) |

店员接口需在请求头带 `X-Token: <登录返回的token>`。

## 后续可扩展(已留好位置，未接真实接口)

- **短信通知**:预约成功/到店提醒，在 `create_booking` 成功后加一行短信发送调用即可(对接阿里云/腾讯云短信)
- **在线支付**:开单页的"微信/支付宝"目前只做记账；要真收款可接入微信支付 JSAPI(需商户号+服务号)
- **微信小程序版**:后端 API 都是标准 REST，小程序端直接复用，无需改后端
- **会员/次卡**:加 `members` 表，开单时扣次，统计里加会员维度
- **技师排班**:预约加技师字段，时间段按技师做容量控制(目前同一时段可多人预约)

## 目录结构

```
yangsheng-app/
├── backend/app.py        # 全部后端:建表/接口/静态页托管
├── frontend/index.html   # 全部前端:顾客端+店员端单页 H5
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── data/                 # SQLite 数据库文件(运行时生成,已挂 volume)
└── README.md
```
