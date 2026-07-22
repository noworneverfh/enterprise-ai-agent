import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Device,
    DeviceAlarmRecord,
    DeviceRuntimeData,
    DeviceRiskTimeline,
    DiagnosisRecord,
    DiagnosisReport,
    MaintenanceRecord,
    RiskEvent,
)
from app.models.document import KnowledgeDocument  # noqa: E402
from app.models.knowledge_structured import (  # noqa: E402
    FaultCause,
    FaultKnowledgeEntry,
    InspectionStep,
    MaintenanceAction,
    MaintenanceCase,
)
from app.services.knowledge import create_document_from_file, delete_document  # noqa: E402


DEMO_DEVICES = [
    {
        "device_code": "DEV-002",
        "name": "Motor Drive B",
        "device_type": "motor",
        "location": "Workshop B",
        "is_online": True,
        "runtime": {
            "temperature": 54.8,
            "voltage": 229.4,
            "current": 9.6,
            "vibration": 0.36,
            "status": "normal",
        },
        "alarm": {
            "alarm_code": "E404",
            "alarm_level": "medium",
            "message": "通信异常，设备与控制器之间存在间歇性连接失败。",
            "is_resolved": False,
        },
    },
    {
        "device_code": "DEV-003",
        "name": "Temperature Sensor C",
        "device_type": "sensor",
        "location": "Workshop C",
        "is_online": True,
        "runtime": {
            "temperature": 72.5,
            "voltage": 24.1,
            "current": 1.2,
            "vibration": 0.05,
            "status": "warning",
        },
        "alarm": {
            "alarm_code": "E101",
            "alarm_level": "high",
            "message": "温度异常，传感器区域温度超过安全阈值。",
            "is_resolved": False,
        },
    },
    {
        "device_code": "DEV-004",
        "name": "Air Compressor D",
        "device_type": "compressor",
        "location": "Workshop D",
        "is_online": True,
        "runtime": {
            "temperature": 43.2,
            "voltage": 231.2,
            "current": 6.1,
            "vibration": 0.21,
            "status": "normal",
        },
        "alarm": None,
    },
    {
        "device_code": "DEV-005",
        "name": "Vibration Motor E",
        "device_type": "motor",
        "location": "Workshop E",
        "is_online": True,
        "runtime": {
            "temperature": 55.0,
            "voltage": 230.5,
            "current": 5.8,
            "vibration": 0.62,
            "status": "normal",
        },
        "alarm": {
            "alarm_code": "E201",
            "alarm_level": "medium",
            "message": "振动异常，设备振动值超过安全范围。",
            "is_resolved": False,
        },
    },
    {
        "device_code": "DEV-006",
        "name": "Hydraulic Pump F",
        "device_type": "pump",
        "location": "Workshop F",
        "is_online": True,
        "runtime": {
            "temperature": 58.2,
            "voltage": 228.7,
            "current": 7.2,
            "vibration": 0.31,
            "status": "maintenance",
        },
        "alarm": {
            "alarm_code": "E302",
            "alarm_level": "medium",
            "message": "液压压力波动，泵站出口压力存在周期性下降。",
            "is_resolved": False,
        },
    },
    {
        "device_code": "DEV-007",
        "name": "Conveyor Gearbox G",
        "device_type": "gearbox",
        "location": "Workshop G",
        "is_online": True,
        "runtime": {
            "temperature": 64.0,
            "voltage": 230.1,
            "current": 6.8,
            "vibration": 0.48,
            "status": "warning",
        },
        "alarm": {
            "alarm_code": "E501",
            "alarm_level": "high",
            "message": "润滑异常，减速箱温度升高并伴随振动上升。",
            "is_resolved": False,
        },
    },
    {
        "device_code": "DEV-008",
        "name": "Cooling Fan H",
        "device_type": "fan",
        "location": "Workshop H",
        "is_online": True,
        "runtime": {
            "temperature": 38.5,
            "voltage": 221.6,
            "current": 3.4,
            "vibration": 0.18,
            "status": "normal",
        },
        "alarm": None,
    },
    {
        "device_code": "DEV-009",
        "name": "PLC Gateway I",
        "device_type": "gateway",
        "location": "Control Room",
        "is_online": True,
        "runtime": {
            "temperature": 41.6,
            "voltage": 24.0,
            "current": 0.8,
            "vibration": 0.02,
            "status": "normal",
        },
        "alarm": {
            "alarm_code": "E404",
            "alarm_level": "low",
            "message": "通信链路波动，PLC网关出现短时采集延迟。",
            "is_resolved": False,
        },
    },
]


DEMO_KNOWLEDGE_DOCUMENTS = {
    "e101_maintenance_manual.md": """# E101 温度异常维护手册

## 适用设备
温度传感器、控制柜、驱动单元、电机外壳测温点。

## 故障说明
E101 表示设备温度超过安全阈值或温升趋势异常。该故障通常发生在散热能力下降、环境温度升高、设备持续高负载或温度传感器读数偏移时。

## 触发条件
- 温度持续高于 60℃。
- 温度在短时间内快速上升，并伴随报警记录。
- 温度读数与现场测温结果存在明显偏差。

## 参数表现
- 温度超过安全范围。
- 电流可能同步升高。
- 设备状态通常从 normal 变为 warning。

## 常见原因排序
1. 散热风道堵塞或滤网积尘。
2. 设备负载过高导致温升过快。
3. 环境通风不足或局部热源靠近设备。
4. 温度传感器安装位置异常或读数漂移。

## 排查流程
1. 复核实时温度、报警时间和设备运行负载。
2. 检查风扇、通风口、滤网和散热片积尘情况。
3. 使用外部测温仪校验传感器读数。
4. 对比最近维护记录，确认是否存在重复温度异常。
5. 若温度持续升高，应降低负载或停机检查。

## 处理方案
- 清理散热通道和滤网。
- 降低设备负载并观察温度回落。
- 校验或更换异常温度传感器。
- 对重复温度异常设备建立重点巡检计划。

## 安全注意事项
温度超过安全阈值时不要长时间带故障运行。现场检查前应确认设备负载状态，必要时执行停机和挂牌流程。

## 维护周期
温度传感器和散热通道建议每月巡检一次，高温季节提高到每两周一次。

## 历史案例
- Workshop C 的温度传感器曾因滤网堵塞触发 E101，清理滤网并复核测温后恢复正常。
- 某控制柜因安装位置靠近热源导致温度误报，调整安装位置后报警消失。
""",
    "e201_vibration_manual.md": """# E201 振动异常维护手册

## 适用设备
电机、泵、风机、压缩机、输送线旋转部件。

## 故障说明
E201 表示设备振动值超过安全范围。该故障常见于机械松动、轴承磨损、联轴器不同心、转轴偏移或负载不平衡。

## 触发条件
- 振动值超过 0.4 mm/s。
- 振动值连续上升，并伴随噪声、温升或电流波动。
- 振动异常与负载变化同步出现。

## 参数表现
- 振动超过阈值。
- 温度可能接近阈值。
- 电流通常不一定异常，但在机械卡滞时可能升高。

## 常见原因排序
1. 地脚螺栓松动或安装基础异常。
2. 联轴器不同心。
3. 轴承磨损或润滑不足。
4. 转子不平衡或负载端卡滞。

## 排查流程
1. 检查振动值是否超过 0.4 mm/s。
2. 检查电机底座、固定螺栓和基础状态。
3. 检查联轴器同心度和轴承温度。
4. 检查负载端是否存在卡滞或偏载。
5. 对照历史维修记录，确认是否为重复振动问题。

## 处理方案
- 暂停高负载运行，避免振动扩大。
- 紧固安装部件并复核联轴器。
- 轴承磨损时安排更换或润滑维护。
- 处理后持续观察振动趋势不少于 30 分钟。

## 安全注意事项
振动持续升高可能导致机械损伤扩大，现场人员应避免靠近高速旋转部件。

## 维护周期
旋转设备建议每周巡检振动，每季度进行联轴器和轴承状态复核。

## 历史案例
- DEV-005 曾出现 0.62 mm/s 振动异常，现场检查发现底座螺栓松动，紧固后振动下降。
- 某风机因轴承润滑不足导致振动升高，补充润滑脂并观察后报警解除。
""",
    "e203_controller_manual.md": """# E203 电机运行异常控制器手册

## 适用设备
电机、驱动器、变频器、输送线驱动单元。

## 故障说明
E203 表示电机运行状态异常，可能与电机过载、电流波动、控制器保护动作、机械阻力过大或驱动参数异常有关。

## 触发条件
- 电流超过额定运行范围。
- 电机温升明显并伴随控制器报警。
- 负载突变或机械传动链路阻力增大。
- 控制器出现保护动作或重复复位。

## 参数表现
- 电流超过 8A 或短时波动明显。
- 温度可能接近或超过安全阈值。
- 振动可能随机械阻力增加而升高。

## 常见原因排序
1. 电机过载运行。
2. 机械传动链路卡滞或阻力增大。
3. 控制器保护参数配置不合理。
4. 电机接线、驱动模块或变频器异常。

## 排查流程
1. 同时检查电流、电压、振动和温度。
2. 确认电机是否过载、卡滞或负载突变。
3. 查看控制器报警记录和保护参数。
4. 检查机械传动链路、皮带、轴承和负载端。
5. 与历史维修记录对比，确认是否重复发生。

## 处理方案
- 降低负载并观察电流是否恢复正常。
- 检查电机接线、控制器模块和驱动参数。
- 清理或修复机械阻力异常部位。
- 报警持续存在时安排电气工程师现场复核。

## 安全注意事项
电机过流或控制器保护动作频繁时，不建议强制复位继续运行。

## 维护周期
驱动器参数建议每季度核验一次，电机负载链路每月巡检一次。

## 历史案例
- DEV-001 出现 E203 后伴随电流升高，现场发现传动链路阻力偏大，清理后恢复。
- 某驱动控制器参数误配置导致保护动作频繁，重新校验参数后报警消除。
""",
    "e302_hydraulic_pressure_manual.md": """# E302 液压压力波动维护手册

## 适用设备
液压泵站、液压执行机构、油压控制单元。

## 故障说明
E302 表示液压系统压力存在异常波动，可能导致执行机构动作不稳定、响应延迟或压力保护动作。

## 触发条件
- 出口压力周期性下降。
- 泵站电流或温度接近阈值。
- 执行机构动作速度不稳定。
- 油液温度升高后压力波动加剧。

## 参数表现
- 温度接近 60℃。
- 电流接近上限但未必超限。
- 振动可能轻微升高。

## 常见原因排序
1. 液压油位不足或油液污染。
2. 吸油滤芯堵塞。
3. 泵体磨损导致容积效率下降。
4. 溢流阀或压力调节阀动作不稳定。
5. 管路存在泄漏或接头松动。

## 排查流程
1. 检查油位、油液颜色和污染情况。
2. 检查吸油滤芯、回油滤芯压差。
3. 观察压力表波动周期和负载动作节拍。
4. 检查泵体异响、温升和振动。
5. 检查阀组、管路接头和密封件是否泄漏。

## 处理方案
- 补充或更换液压油。
- 更换堵塞滤芯。
- 调整或检修溢流阀。
- 泵体磨损严重时安排泵站检修。

## 安全注意事项
检修液压系统前必须释放残余压力，禁止带压拆卸管路。

## 维护周期
液压油每季度抽样检查，滤芯按压差或运行小时数更换。

## 历史案例
- DEV-006 出现 E302 后发现吸油滤芯堵塞，更换滤芯后压力恢复稳定。
- 某液压站因油液污染导致阀芯卡滞，清洗阀组并更换油液后故障解除。
""",
    "e404_sensor_manual.md": """# E404 通信异常维护手册

## 适用设备
PLC网关、传感器、远程IO模块、驱动控制器。

## 故障说明
E404 表示设备通信异常。常见原因包括通信线缆松动、网络中断、控制器超时、地址冲突或通信模块故障。

## 触发条件
- 设备上报超时。
- 控制器连续多次读取失败。
- 状态数据间歇性缺失。
- 网关日志出现连接重试或会话断开。

## 参数表现
- 运行参数可能仍在范围内，但状态采集不连续。
- 设备可显示 warning。
- 多个设备同时出现时应优先检查网络链路。

## 常见原因排序
1. 通信线缆松动或端子接触不良。
2. 网关、交换机或控制器网络异常。
3. 设备地址、波特率或协议配置不一致。
4. 通信模块故障。

## 排查流程
1. 检查网线、端子接线和连接器状态。
2. 核对设备地址、波特率和通信协议。
3. 检查网关、控制器和交换机日志。
4. 判断异常是间歇性还是持续性。
5. 若同一网络段多设备异常，优先检查交换机和网关。

## 处理方案
- 固定通信线缆并清理端子。
- 确认安全后重启网关或控制器。
- 重新核对通信配置。
- 故障持续时更换通信模块或备用端口。

## 安全注意事项
通信异常可能导致监控盲区，现场应加强人工巡检。

## 维护周期
通信端子建议每月巡检，网关日志建议每周抽查。

## 历史案例
- DEV-002 因交换机端口接触不良触发 E404，更换端口后恢复。
- 某传感器地址冲突导致间歇通信失败，重新分配地址后报警解除。
""",
    "e501_gearbox_lubrication_manual.md": """# E501 减速箱润滑异常维护手册

## 适用设备
输送线减速箱、齿轮箱、重载传动机构。

## 故障说明
E501 表示润滑状态异常，通常表现为减速箱温度升高、振动上升、噪声变大或油位异常。该故障若不及时处理，可能导致齿轮磨损和轴承损伤。

## 触发条件
- 减速箱温度超过 60℃。
- 振动值超过 0.4 mm/s。
- 油位低于观察窗下限。
- 油液颜色变深、乳化或含金属碎屑。

## 参数表现
- 温度超过安全阈值。
- 振动接近或超过阈值。
- 电流可能略有升高。

## 常见原因排序
1. 润滑油不足或油品不符合要求。
2. 齿轮啮合异常或轴承磨损。
3. 密封件老化导致漏油。
4. 长时间高负载运行导致油温升高。
5. 通气帽堵塞造成箱体压力异常。

## 排查流程
1. 检查油位、油色和是否存在漏油。
2. 检查减速箱外壳温度和异常噪声。
3. 检查轴承座、齿轮啮合和联轴器状态。
4. 检查通气帽、密封件和油封。
5. 对比历史维护周期，确认是否超期未换油。

## 处理方案
- 立即补充或更换符合规格的润滑油。
- 清理通气帽并检查密封件。
- 若温度和振动持续异常，安排停机拆检。
- 建立换油和油液检测记录。

## 安全注意事项
减速箱高温时不要直接触摸外壳。停机检修前应确认输送线已锁定并释放机械张力。

## 维护周期
重载减速箱建议每月检查油位，每半年进行油液检测。

## 历史案例
- DEV-007 出现 E501 后检查发现油位低于观察窗下限，补油并清理通气帽后温度回落。
- 某输送线减速箱因油封老化漏油，导致温度和振动同时升高，更换油封并换油后恢复。
""",
    "plant_preventive_maintenance_playbook.md": """# 车间预防性维护作业指南

## 适用范围
适用于 Workshop B 至 Workshop H 的电机、泵、风机、压缩机、传感器和网关设备。

## 巡检目标
通过周期性检查温度、电流、振动、通信状态和报警记录，提前发现设备退化趋势，减少非计划停机。

## 日常巡检
1. 检查设备在线状态和最近报警。
2. 记录温度、电压、电流和振动。
3. 对比安全阈值和最近一次巡检记录。
4. 对 warning 状态设备进行复核。
5. 未处理报警必须登记责任人和预计处理时间。

## 风险分级
- 高风险：存在高等级未处理报警，或温度、振动、电流明显越限。
- 中风险：存在中等级报警，或参数接近安全阈值。
- 低风险：设备在线且参数轻微波动。
- 正常：无报警且参数在安全范围内。

## 维修闭环
每一次 AI 诊断建议必须与现场处理结果关联，包括实际处理动作、最终根因、是否解决和复查结论。该记录可沉淀为后续相似故障案例。

## 管理要求
异常设备需要在班次交接时重点说明。重复报警设备应纳入专项维护计划。
""",
    "industrial_alarm_triage_guide.md": """# 工业设备报警分诊指南

## 目的
帮助运维人员在多设备同时报警时快速判断处理优先级。

## 分诊原则
1. 优先处理高风险设备。
2. 优先处理影响安全、生产连续性和数据采集完整性的报警。
3. 参数越限与报警同时出现时，应视为更高优先级。
4. 通信异常可能导致数据不完整，应结合现场状态确认。

## 典型报警处理顺序
- E101 温度异常：先确认温度是否持续升高，再检查散热和传感器。
- E201 振动异常：先降低负载，再检查机械连接和轴承。
- E203 电机运行异常：先检查电流和负载链路，再检查控制器。
- E302 液压压力波动：先检查油位和滤芯，再检查泵体与阀组。
- E404 通信异常：先检查网络链路，再核对配置。
- E501 润滑异常：先检查油位和油品，再安排减速箱检修。

## 输出要求
诊断报告必须说明已确认事实、可能原因、验证方法、处理建议和引用的维修资料。没有知识库依据时，不得伪造来源。
""",
}

DEMO_KNOWLEDGE_DOCUMENTS.update(
    {
        "enterprise_e101_temperature_abnormal_manual.md": DEMO_KNOWLEDGE_DOCUMENTS["e101_maintenance_manual.md"],
        "enterprise_e201_vibration_abnormal_manual.md": DEMO_KNOWLEDGE_DOCUMENTS["e201_vibration_manual.md"],
        "enterprise_e203_motor_abnormal_manual.md": DEMO_KNOWLEDGE_DOCUMENTS["e203_controller_manual.md"],
        "enterprise_e404_communication_abnormal_manual.md": DEMO_KNOWLEDGE_DOCUMENTS["e404_sensor_manual.md"],
    }
)


STRUCTURED_FAULT_KNOWLEDGE = [
    {
        "fault_code": "E101",
        "fault_name": "温度异常",
        "severity": "high",
        "device_type": "sensor",
        "document": "enterprise_e101_temperature_abnormal_manual.md",
        "description": "设备温度超过安全阈值，常见于散热不足、环境温度过高、负载异常或传感器漂移。",
        "trigger_conditions": ["温度持续高于 60℃", "温度快速上升并伴随报警", "传感器读数与现场测温不一致"],
        "causes": [
            ("散热滤网堵塞", "滤网积尘会降低散热效率，导致传感器区域温度升高。", "检查滤网、风道和散热风扇状态。"),
            ("传感器读数漂移", "安装位置或元件老化可能导致读数偏高。", "使用外部测温仪复核读数。"),
            ("环境通风不足", "局部热源或通风不足会造成持续温升。", "检查设备周边热源和通风条件。"),
        ],
        "steps": [
            ("复核温度数据", "确认温度是否持续超过 60℃。", "温度继续升高时应降低负载或停机检查。"),
            ("检查散热链路", "风扇、滤网和风道无堵塞。", "检查前确认设备运行状态安全。"),
            ("校验传感器", "现场测温与系统读数偏差在允许范围内。", "避免接触高温部件。"),
        ],
        "actions": [
            ("清理滤网和风道", "温度升高且散热链路存在积尘时执行。"),
            ("更换或校准温度传感器", "现场测温与系统读数偏差明显时执行。"),
            ("优化通风或降低负载", "环境温度偏高或设备长期高负载时执行。"),
        ],
        "cases": [
            ("DEV-003", "传感器区域温度升至 72℃ 并触发 E101。", "散热滤网堵塞", "清理滤网并复核测温。", "温度回落至 48℃，报警解除。"),
            ("Workshop C Sensor", "高温季节多次出现温度误报。", "传感器安装点靠近热源", "调整安装位置并增加隔热挡板。", "后续两周未复发。"),
        ],
    },
    {
        "fault_code": "E201",
        "fault_name": "振动异常",
        "severity": "medium",
        "device_type": "motor",
        "document": "enterprise_e201_vibration_abnormal_manual.md",
        "description": "旋转设备振动值超过安全范围，可能与机械松动、联轴器不同心或轴承磨损有关。",
        "trigger_conditions": ["振动值超过 0.4mm/s", "振动持续上升", "伴随噪声或温升"],
        "causes": [
            ("底座固定松动", "安装基础松动会放大设备振动。", "检查地脚螺栓和底座状态。"),
            ("联轴器不同心", "同心度偏差会造成周期性振动。", "复核联轴器同心度。"),
            ("轴承磨损", "轴承磨损会导致振动和温度同步升高。", "检查轴承温度、噪声和润滑状态。"),
        ],
        "steps": [
            ("确认振动阈值", "振动值是否超过 0.4mm/s。", "避免靠近高速旋转部件。"),
            ("检查机械连接", "螺栓紧固、底座无松动。", "必要时降低负载后检查。"),
            ("复核轴承状态", "轴承无异常噪声和过热。", "停机后再进行近距离检查。"),
        ],
        "actions": [
            ("紧固安装基础", "发现底座或螺栓松动时执行。"),
            ("校正联轴器", "振动呈周期性且同心度偏差时执行。"),
            ("更换或润滑轴承", "轴承磨损或润滑不足时执行。"),
        ],
        "cases": [
            ("DEV-005", "振动值达到 0.62mm/s。", "安装基础松动", "紧固底座螺栓并复核联轴器。", "振动下降但需继续观察。"),
            ("Motor Line E", "负载提升后振动持续升高。", "联轴器同心度偏差", "重新找正联轴器。", "振动恢复到安全范围。"),
        ],
    },
    {
        "fault_code": "E302",
        "fault_name": "液压压力波动",
        "severity": "medium",
        "device_type": "pump",
        "document": "e302_hydraulic_pressure_manual.md",
        "description": "液压系统压力存在周期性波动，可能导致执行机构动作不稳定。",
        "trigger_conditions": ["出口压力周期性下降", "执行机构响应延迟", "油温升高后波动加剧"],
        "causes": [
            ("吸油滤芯堵塞", "滤芯堵塞会造成吸油不足和压力波动。", "检查吸油滤芯压差。"),
            ("油液污染", "油液污染可能导致阀芯卡滞。", "检查油液颜色和污染等级。"),
            ("压力阀动作不稳定", "溢流阀或压力调节阀异常会造成压力波动。", "观察压力表波动与阀组动作。"),
        ],
        "steps": [
            ("检查油位和油液", "油位在标准范围内，油液无明显污染。", "检修前释放残余压力。"),
            ("检查滤芯", "滤芯压差不超过维护阈值。", "禁止带压拆卸滤芯。"),
            ("检查压力阀", "压力波动与阀组动作无异常同步。", "按液压安全规范操作。"),
        ],
        "actions": [
            ("更换吸油滤芯", "滤芯压差异常或堵塞时执行。"),
            ("更换液压油", "油液污染或乳化时执行。"),
            ("检修压力调节阀", "压力波动持续存在时执行。"),
        ],
        "cases": [
            ("DEV-006", "泵站出口压力周期性下降。", "吸油滤芯堵塞", "更换滤芯并补充液压油。", "压力波动明显降低。"),
            ("Hydraulic Station F", "执行机构动作迟缓。", "油液污染导致阀芯卡滞", "清洗阀组并更换油液。", "动作恢复稳定。"),
        ],
    },
    {
        "fault_code": "E404",
        "fault_name": "通信异常",
        "severity": "medium",
        "device_type": "gateway",
        "document": "enterprise_e404_communication_abnormal_manual.md",
        "description": "设备通信链路不稳定，可能造成状态数据缺失或采集延迟。",
        "trigger_conditions": ["设备上报超时", "控制器读取失败", "网关日志出现重试或断开"],
        "causes": [
            ("通信线缆接触不良", "接线松动会导致间歇性通信失败。", "检查网线、端子和连接器。"),
            ("网关或交换机异常", "网络设备异常会影响多个采集点。", "检查网关和交换机日志。"),
            ("地址或协议配置不一致", "配置冲突会导致读取失败。", "核对地址、波特率和协议。"),
        ],
        "steps": [
            ("检查物理连接", "线缆和端子连接牢固。", "检查前注意电气安全。"),
            ("核对通信配置", "地址、波特率和协议与控制器一致。", None),
            ("检查网络日志", "无连续断线和重连记录。", None),
        ],
        "actions": [
            ("固定通信线缆", "发现接触不良或线缆松动时执行。"),
            ("切换备用网口", "交换机端口异常时执行。"),
            ("修正通信配置", "地址或协议配置不一致时执行。"),
        ],
        "cases": [
            ("DEV-002", "设备与控制器间歇性连接失败。", "交换机端口接触不良", "更换交换机端口并固定线缆。", "通信恢复稳定。"),
            ("DEV-009", "PLC网关短时采集延迟。", "网关端口松动", "切换备用端口并核对地址。", "采集数据恢复连续。"),
        ],
    },
    {
        "fault_code": "E501",
        "fault_name": "润滑异常",
        "severity": "high",
        "device_type": "gearbox",
        "document": "e501_gearbox_lubrication_manual.md",
        "description": "减速箱润滑状态异常，通常伴随温度升高、振动上升或油位异常。",
        "trigger_conditions": ["减速箱温度超过 60℃", "振动超过 0.4mm/s", "油位低于观察窗下限"],
        "causes": [
            ("润滑油位不足", "油位不足会导致齿轮和轴承润滑不充分。", "检查油位观察窗和漏油点。"),
            ("油封老化漏油", "油封失效会造成持续缺油。", "检查油封、密封面和箱体外部油迹。"),
            ("齿轮或轴承磨损", "磨损会导致温度和振动同步升高。", "检查噪声、油液金属碎屑和振动趋势。"),
        ],
        "steps": [
            ("检查油位油色", "油位正常，油液无乳化或金属碎屑。", "高温外壳禁止直接触摸。"),
            ("检查漏油和通气帽", "密封件无漏油，通气帽无堵塞。", "停机锁定后检查。"),
            ("检查齿轮箱状态", "无异常噪声和持续高温。", "必要时安排停机拆检。"),
        ],
        "actions": [
            ("补充或更换润滑油", "油位不足或油品异常时执行。"),
            ("更换油封", "发现持续漏油时执行。"),
            ("安排停机拆检", "温度和振动持续异常时执行。"),
        ],
        "cases": [
            ("DEV-007", "减速箱温度 64℃ 且振动 0.48mm/s。", "润滑油位不足", "补油并清理通气帽。", "温度回落但需继续检查油封。"),
            ("Conveyor Gearbox G", "输送线运行中出现异常噪声。", "轴承磨损", "停机更换轴承并更换润滑油。", "恢复稳定运行。"),
        ],
    },
]


def seed_demo_data(db: Session) -> dict[str, int]:
    """Create deterministic enterprise demo data without duplicating rows."""

    created_devices = 0
    created_runtime_rows = 0
    created_alarm_rows = 0
    created_knowledge_documents = 0
    refreshed_knowledge_documents = 0
    created_diagnosis_records = 0
    created_maintenance_records = 0
    created_risk_events = 0
    created_risk_points = 0
    created_structured_knowledge = 0
    now = datetime.utcnow()
    devices_by_code: dict[str, Device] = {}

    for index, item in enumerate(DEMO_DEVICES, start=1):
        device = db.scalar(
            select(Device).where(Device.device_code == item["device_code"])
        )
        if device is None:
            device = Device(
                device_code=item["device_code"],
                name=item["name"],
                device_type=item["device_type"],
                location=item["location"],
                is_online=item["is_online"],
            )
            db.add(device)
            db.flush()
            created_devices += 1
        else:
            device.name = item["name"]
            device.device_type = item["device_type"]
            device.location = item["location"]
            device.is_online = item["is_online"]
        devices_by_code[device.device_code] = device

        runtime_exists = db.scalar(
            select(DeviceRuntimeData.id)
            .where(DeviceRuntimeData.device_id == device.id)
            .limit(1)
        )
        if runtime_exists is None:
            db.add(
                DeviceRuntimeData(
                    device_id=device.id,
                    recorded_at=now - timedelta(minutes=max(0, 12 - index)),
                    **item["runtime"],
                )
            )
            created_runtime_rows += 1

        alarm = item["alarm"]
        if alarm is not None:
            alarm_exists = db.scalar(
                select(DeviceAlarmRecord)
                .where(DeviceAlarmRecord.device_id == device.id)
                .where(DeviceAlarmRecord.alarm_code == alarm["alarm_code"])
                .where(DeviceAlarmRecord.is_resolved.is_(False))
                .limit(1)
            )
            if alarm_exists is None:
                db.add(
                    DeviceAlarmRecord(
                        device_id=device.id,
                        occurred_at=now - timedelta(minutes=max(0, 8 - index)),
                        **alarm,
                    )
                )
                created_alarm_rows += 1
            else:
                alarm_exists.message = alarm["message"]
                alarm_exists.alarm_level = alarm["alarm_level"]

    db.flush()

    for code, device in devices_by_code.items():
        item = _device_item(code)
        health = _demo_health(item)
        existing_point = db.scalar(
            select(DeviceRiskTimeline.id)
            .where(DeviceRiskTimeline.device_id == device.id)
            .limit(1)
        )
        if existing_point is None:
            for offset, score in enumerate(_risk_series(health["risk_score"])):
                db.add(
                    DeviceRiskTimeline(
                        device_id=device.id,
                        risk_level=health["risk_level"],
                        risk_score=score,
                        alarm_count=1 if item["alarm"] else 0,
                        abnormal_parameters=health["abnormal_parameters"],
                        recorded_at=now - timedelta(days=5 - offset),
                    )
                )
                created_risk_points += 1

    db.commit()

    uploads_dir = Path(settings.upload_directory)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in DEMO_KNOWLEDGE_DOCUMENTS.items():
        existing_document = db.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.original_filename == filename)
            .limit(1)
        )
        if existing_document is not None:
            if not existing_document.storage_filename.startswith("seed_"):
                continue

            existing_path = (
                Path(existing_document.file_path)
                if existing_document.file_path is not None
                else uploads_dir / existing_document.storage_filename
            )
            if (
                existing_path.is_file()
                and existing_path.read_text(encoding="utf-8") == content
            ):
                continue

            delete_document(db, existing_document)
            refreshed_knowledge_documents += 1

        file_path = uploads_dir / f"seed_{filename}"
        file_path.write_text(content, encoding="utf-8")
        create_document_from_file(
            db=db,
            file_path=file_path,
            original_filename=filename,
        )
        created_knowledge_documents += 1

    db.commit()

    created_structured_knowledge += _seed_structured_knowledge(db)
    db.commit()

    created_diagnosis_records += _seed_diagnosis_records(db, devices_by_code, now)
    created_maintenance_records += _seed_maintenance_records(db, devices_by_code, now)
    created_risk_events += _seed_risk_events(db, devices_by_code, now)
    db.commit()

    return {
        "created_devices": created_devices,
        "created_runtime_rows": created_runtime_rows,
        "created_alarm_rows": created_alarm_rows,
        "created_knowledge_documents": created_knowledge_documents,
        "refreshed_knowledge_documents": refreshed_knowledge_documents,
        "created_diagnosis_records": created_diagnosis_records,
        "created_maintenance_records": created_maintenance_records,
        "created_risk_events": created_risk_events,
        "created_risk_points": created_risk_points,
        "created_structured_knowledge": created_structured_knowledge,
    }


def _seed_structured_knowledge(db: Session) -> int:
    created = 0
    documents_by_name = {
        document.original_filename: document
        for document in db.scalars(select(KnowledgeDocument)).all()
    }

    for item in STRUCTURED_FAULT_KNOWLEDGE:
        entry = db.scalar(
            select(FaultKnowledgeEntry)
            .where(FaultKnowledgeEntry.fault_code == item["fault_code"])
            .where(FaultKnowledgeEntry.device_type == item["device_type"])
            .limit(1)
        )
        document = documents_by_name.get(item["document"])
        if entry is None:
            entry = FaultKnowledgeEntry(
                document_id=document.id if document else None,
                fault_code=item["fault_code"],
                fault_name=item["fault_name"],
                description=item["description"],
                severity=item["severity"],
                device_type=item["device_type"],
                trigger_conditions=item["trigger_conditions"],
            )
            db.add(entry)
            db.flush()
            created += 1
        else:
            entry.document_id = document.id if document else entry.document_id
            entry.fault_name = item["fault_name"]
            entry.description = item["description"]
            entry.severity = item["severity"]
            entry.trigger_conditions = item["trigger_conditions"]

        if not entry.causes:
            for priority, (cause, evidence, verification) in enumerate(item["causes"], start=1):
                db.add(
                    FaultCause(
                        fault_entry_id=entry.id,
                        cause=cause,
                        priority=priority,
                        evidence=evidence,
                        verification_method=verification,
                    )
                )
        if not entry.inspection_steps:
            for order, (operation, expected_result, safety_requirement) in enumerate(item["steps"], start=1):
                db.add(
                    InspectionStep(
                        fault_entry_id=entry.id,
                        order=order,
                        operation=operation,
                        expected_result=expected_result,
                        safety_requirement=safety_requirement,
                    )
                )
        if not entry.maintenance_actions:
            for priority, (action, condition) in enumerate(item["actions"], start=1):
                db.add(
                    MaintenanceAction(
                        fault_entry_id=entry.id,
                        priority=priority,
                        action=action,
                        condition=condition,
                    )
                )

        existing_cases = {
            (case.device, case.fault, case.root_cause)
            for case in db.scalars(
                select(MaintenanceCase).where(MaintenanceCase.fault_entry_id == entry.id)
            ).all()
        }
        for device, symptom, root_cause, solution, result in item["cases"]:
            key = (device, item["fault_code"], root_cause)
            if key in existing_cases:
                continue
            db.add(
                MaintenanceCase(
                    fault_entry_id=entry.id,
                    device=device,
                    fault=item["fault_code"],
                    symptom=symptom,
                    root_cause=root_cause,
                    solution=solution,
                    result=result,
                )
            )
    return created


def _seed_diagnosis_records(
    db: Session,
    devices_by_code: dict[str, Device],
    now: datetime,
) -> int:
    created = 0
    specs = [
        (
            "demo-report-dev003-e101",
            "DEV-003",
            "E101",
            "high",
            "分析设备温度异常原因",
            "DEV-003 温度超过安全阈值，初步判断存在散热能力下降或传感器异常风险。",
        ),
        (
            "demo-report-dev005-e201",
            "DEV-005",
            "E201",
            "medium",
            "分析设备振动异常原因",
            "DEV-005 振动值超过安全范围，建议优先检查安装基础和轴承状态。",
        ),
        (
            "demo-report-dev006-e302",
            "DEV-006",
            "E302",
            "medium",
            "分析液压泵压力波动原因",
            "DEV-006 出现液压压力波动，建议检查油位、滤芯和压力调节阀状态。",
        ),
        (
            "demo-report-dev007-e501",
            "DEV-007",
            "E501",
            "high",
            "分析减速箱润滑异常原因",
            "DEV-007 温度和振动同步升高，存在润滑不足或齿轮箱磨损风险。",
        ),
        (
            "demo-report-dev009-e404",
            "DEV-009",
            "E404",
            "low",
            "分析网关通信波动原因",
            "DEV-009 出现短时通信延迟，建议检查PLC网关链路和网络配置。",
        ),
        (
            "demo-report-fleet-risk",
            None,
            None,
            "high",
            "分析当前所有设备风险",
            "已完成全厂设备风险巡检，DEV-003 和 DEV-007 需要优先现场复核。",
        ),
    ]
    for index, (report_id, device_code, alarm_code, risk_level, query, summary) in enumerate(specs):
        if db.scalar(select(DiagnosisRecord.id).where(DiagnosisRecord.report_id == report_id)):
            continue
        report_v2 = _single_report_v2(device_code, alarm_code, risk_level, summary)
        response_json = {
            "response": _legacy_response_payload(device_code, alarm_code, risk_level, summary, report_v2),
            "rag_sources": _rag_sources(alarm_code),
            "tools_used": (
                ["get_device_status", "get_device_alarms", "search_knowledge"]
                if device_code
                else ["list_devices", "get_device_status", "get_device_alarms", "search_knowledge"]
            ),
            "confidence": 82,
        }
        record = DiagnosisRecord(
            report_id=report_id,
            device_code=device_code,
            alarm_code=alarm_code,
            risk_level=risk_level,
            status="completed",
            query=query,
            problem_summary=summary,
            response_json=response_json,
            duration_ms=1180 + index * 220,
            created_at=now - timedelta(hours=index + 1),
        )
        db.add(record)
        db.flush()
        db.add(
            DiagnosisReport(
                report_id=report_id,
                diagnosis_record_id=record.id,
                report_version="2.0",
                device_id=devices_by_code[device_code].id if device_code else None,
                risk_level=risk_level,
                risk_score=report_v2["risk"]["score"],
                confirmed_facts=report_v2["confirmed_facts"],
                parameter_observations=report_v2["parameter_observations"],
                cause_analysis=report_v2["possible_causes"],
                verification_steps=report_v2["verification_steps"],
                action_plan=report_v2["action_plan"],
                citations=report_v2["citations"],
                provider_type="seeded-demo",
                generation_status="completed",
                report_json=report_v2,
                created_at=record.created_at,
            )
        )
        created += 1
    return created


def _seed_maintenance_records(
    db: Session,
    devices_by_code: dict[str, Device],
    now: datetime,
) -> int:
    created = 0
    specs = [
        (
            "DEV-003",
            "清理温度传感器安装区域滤网，并使用外部测温仪复核传感器读数。",
            "散热滤网堵塞",
            True,
            "温度回落到 48℃，连续观察 30 分钟未再次报警。",
            "demo-report-dev003-e101",
        ),
        (
            "DEV-005",
            "紧固电机底座螺栓，复核联轴器同心度，并安排轴承状态复检。",
            "安装基础松动",
            False,
            "振动值下降但仍接近阈值，建议下一班继续复核。",
            "demo-report-dev005-e201",
        ),
        (
            "DEV-006",
            "更换吸油滤芯，补充液压油并复核出口压力波动。",
            "吸油滤芯堵塞",
            True,
            "压力波动明显降低，泵站运行恢复稳定。",
            "demo-report-dev006-e302",
        ),
        (
            "DEV-007",
            "补充减速箱润滑油，清理通气帽，并安排油封泄漏检查。",
            "润滑油位不足",
            False,
            "温度有所回落，但仍需停机窗口完成密封件检查。",
            "demo-report-dev007-e501",
        ),
        (
            "DEV-009",
            "更换PLC网关备用网口，固定通信线缆并核对地址配置。",
            "交换机端口接触不良",
            True,
            "通信延迟消失，采集数据恢复连续。",
            "demo-report-dev009-e404",
        ),
    ]
    for code, action, cause, resolved, result, report_id in specs:
        device = devices_by_code[code]
        exists = db.scalar(
            select(MaintenanceRecord.id)
            .where(MaintenanceRecord.device_id == device.id)
            .where(MaintenanceRecord.actual_action == action)
            .limit(1)
        )
        if exists:
            continue
        db.add(
            MaintenanceRecord(
                device_id=device.id,
                report_id=report_id,
                ai_recommendation={"summary": "根据报警、运行参数和维修知识建议安排现场检查。"},
                actual_action=action,
                confirmed_root_cause=cause,
                resolved=resolved,
                result=result,
                performed_at=now - timedelta(hours=2),
            )
        )
        created += 1
    return created


def _seed_risk_events(
    db: Session,
    devices_by_code: dict[str, Device],
    now: datetime,
) -> int:
    created = 0
    specs = [
        ("demo-risk-dev003-e101", "DEV-003", "temperature_risk", "high", 86, "DEV-003 温度持续超过安全范围，存在高温损伤风险。", "demo-report-dev003-e101"),
        ("demo-risk-dev005-e201", "DEV-005", "vibration_risk", "medium", 68, "DEV-005 振动值超过安全阈值，建议检查机械连接与轴承状态。", "demo-report-dev005-e201"),
        ("demo-risk-dev002-e404", "DEV-002", "communication_risk", "medium", 62, "DEV-002 存在通信异常，可能影响设备状态采集连续性。", None),
        ("demo-risk-dev006-e302", "DEV-006", "hydraulic_pressure_risk", "medium", 64, "DEV-006 液压压力出现周期性波动，建议检查油路和滤芯。", "demo-report-dev006-e302"),
        ("demo-risk-dev007-e501", "DEV-007", "lubrication_risk", "high", 88, "DEV-007 减速箱温度和振动同步升高，存在润滑失效风险。", "demo-report-dev007-e501"),
        ("demo-risk-dev009-e404", "DEV-009", "communication_risk", "low", 42, "DEV-009 出现短时通信延迟，建议纳入网络链路巡检。", "demo-report-dev009-e404"),
    ]
    for event_id, code, event_type, level, score, summary, report_id in specs:
        if db.scalar(select(RiskEvent.id).where(RiskEvent.event_id == event_id)):
            continue
        device = devices_by_code[code]
        db.add(
            RiskEvent(
                event_id=event_id,
                device_id=device.id,
                event_type=event_type,
                risk_level=level,
                risk_score=score,
                summary=summary,
                evidence={
                    "device_code": code,
                    "unresolved_alarm_count": 1,
                    "abnormal_parameters": _demo_health(_device_item(code))["abnormal_parameters"],
                    "trend": "worsening" if code in {"DEV-003", "DEV-005", "DEV-007"} else "stable",
                },
                status="open",
                report_id=report_id,
                created_at=now - timedelta(minutes=20),
            )
        )
        created += 1
    return created


def _legacy_response_payload(
    device_code: str | None,
    alarm_code: str | None,
    risk_level: str,
    summary: str,
    report_v2: dict,
) -> dict:
    return {
        "problem_summary": summary,
        "device": None,
        "device_status": None,
        "recent_alarms": [],
        "risk_level": risk_level,
        "possible_causes": [cause["description"] for cause in report_v2["possible_causes"]],
        "recommended_actions": [action["description"] for action in report_v2["action_plan"]],
        "sources": [source["source"] for source in report_v2["citations"]],
        "tools_used": (
            ["get_device_status", "get_device_alarms", "search_knowledge"]
            if device_code
            else ["list_devices", "get_device_status", "get_device_alarms", "search_knowledge"]
        ),
        "warnings": [],
        "disclaimer": "本报告由工业设备智能运维 AI Agent 平台生成，最终处理需结合现场确认。",
        "report_v2": report_v2,
    }


def _single_report_v2(
    device_code: str | None,
    alarm_code: str | None,
    risk_level: str,
    conclusion: str,
) -> dict:
    profile = _fault_profile(alarm_code)
    score = {"high": 86, "medium": 68, "low": 42, "normal": 18}.get(risk_level, 50)
    citation = _citation(alarm_code)
    return {
        "report_version": "2.0",
        "generation_mode": "deterministic",
        "conclusion": conclusion,
        "risk": {
            "level": risk_level,
            "score": score,
            "breakdown": [
                {"code": "alarm", "label": "未处理报警", "score": 35, "reason": "设备存在未关闭报警。"},
                {"code": "parameter", "label": "参数异常", "score": 35, "reason": f"{profile['label']} 接近或超过安全范围。"},
            ],
        },
        "confirmed_facts": [
            {"fact_id": "device", "category": "device", "label": "设备", "value": device_code or "多设备", "status": "info", "source": "设备台账"},
            {"fact_id": "alarm", "category": "alarm", "label": "报警", "value": f"{alarm_code or '多类报警'} {_alarm_name(alarm_code)}", "status": "warning", "source": "报警记录"},
            {"fact_id": "knowledge", "category": "knowledge", "label": "维修资料", "value": citation["title"], "status": "info", "source": "企业知识库"},
        ],
        "parameter_observations": [
            {
                "parameter": profile["parameter"],
                "label": profile["label"],
                "value": profile["value"],
                "unit": profile["unit"],
                "normal_min": profile["normal_min"],
                "normal_max": profile["normal_max"],
                "status": "critical" if risk_level == "high" else "warning",
                "explanation": f"{profile['label']} 已超过或接近安全阈值，需要现场复核。",
                "observed_at": datetime.utcnow().isoformat(),
            }
        ],
        "possible_causes": [
            {
                "title": _cause_title(alarm_code),
                "description": _cause_description(alarm_code),
                "confidence": "medium",
                "evidence_refs": ["alarm", "knowledge"],
                "verification_method": _verification(alarm_code),
            }
        ],
        "verification_steps": [
            {"order": 1, "title": "复核现场状态", "description": "检查报警是否仍然存在，并确认设备运行参数。", "safety_note": "如参数继续升高，应降低负载或停机检查。"},
            {"order": 2, "title": "按维修资料排查", "description": _verification(alarm_code), "safety_note": None},
        ],
        "action_plan": [
            {"order": 1, "priority": "immediate", "title": "立即复核风险设备", "description": _action(alarm_code), "safety_required": True, "evidence_refs": ["alarm", "knowledge"]},
            {"order": 2, "priority": "planned", "title": "形成处理记录", "description": "现场处理后登记实际根因和处理结果，形成可复用维修记忆。", "safety_required": False, "evidence_refs": ["history"]},
        ],
        "citations": [citation],
        "data_gaps": [],
        "device_context_summary": {"device_code": device_code, "alarm_code": alarm_code},
        "risk_trend": [],
        "historical_cases": [],
        "maintenance_memory_refs": [],
    }


def _rag_sources(alarm_code: str | None) -> list[dict]:
    citation = _citation(alarm_code)
    return [
        {
            "source": citation["source"],
            "filename": citation["source"].split("#")[0],
            "chunk_id": None,
            "chunk_index": None,
            "distance": None,
            "content": citation["excerpt"],
        }
    ]


def _citation(alarm_code: str | None) -> dict:
    mapping = {
        "E101": ("e101_maintenance_manual.md", "E101 温度异常维护手册", "E101 通常与散热不足、环境温度升高、负载过高或传感器异常有关。"),
        "E201": ("e201_vibration_manual.md", "E201 振动异常维护手册", "E201 可能与机械松动、轴承磨损、转轴偏移或安装基础异常有关。"),
        "E203": ("e203_controller_manual.md", "E203 电机运行异常控制器手册", "E203 可能与电机过载、电流波动、控制器保护动作或机械阻力过大有关。"),
        "E302": ("e302_hydraulic_pressure_manual.md", "E302 液压压力波动维护手册", "E302 可能与油位不足、滤芯堵塞、泵体磨损或压力阀动作不稳定有关。"),
        "E404": ("e404_sensor_manual.md", "E404 通信异常维护手册", "E404 通常与通信线缆、网关、控制器超时或通信模块故障有关。"),
        "E501": ("e501_gearbox_lubrication_manual.md", "E501 减速箱润滑异常维护手册", "E501 通常与润滑油不足、油封泄漏、齿轮啮合异常或轴承磨损有关。"),
    }
    filename, title, excerpt = mapping.get(alarm_code or "E203", mapping["E203"])
    return {
        "citation_id": f"citation-{alarm_code or 'fleet'}",
        "source": f"{filename}#维修建议",
        "title": title,
        "excerpt": excerpt,
    }


def _fault_profile(alarm_code: str | None) -> dict:
    profiles = {
        "E101": {"parameter": "temperature", "label": "温度", "value": 72.5, "unit": "℃", "normal_min": 0, "normal_max": 60},
        "E201": {"parameter": "vibration", "label": "振动", "value": 0.62, "unit": "mm/s", "normal_min": 0, "normal_max": 0.4},
        "E203": {"parameter": "current", "label": "电流", "value": 9.6, "unit": "A", "normal_min": 0, "normal_max": 8},
        "E302": {"parameter": "pressure", "label": "液压压力", "value": 11.8, "unit": "MPa", "normal_min": 10, "normal_max": 14},
        "E404": {"parameter": "communication", "label": "通信状态", "value": 1, "unit": "次", "normal_min": 0, "normal_max": 0},
        "E501": {"parameter": "temperature", "label": "减速箱温度", "value": 64.0, "unit": "℃", "normal_min": 0, "normal_max": 60},
    }
    return profiles.get(alarm_code or "E203", profiles["E203"])


def _demo_health(item: dict) -> dict:
    runtime = item["runtime"]
    abnormal = []
    if runtime["temperature"] > 60:
        abnormal.append("temperature")
    if runtime["current"] > 8:
        abnormal.append("current")
    if runtime["vibration"] > 0.4:
        abnormal.append("vibration")
    level = "high" if item["alarm"] and item["alarm"]["alarm_level"] == "high" else "medium" if item["alarm"] else "normal"
    score = 86 if level == "high" else 68 if level == "medium" else 18
    return {"risk_level": level, "risk_score": score, "abnormal_parameters": abnormal}


def _risk_series(current: int) -> list[int]:
    return [max(5, current - 28), max(8, current - 18), max(10, current - 10), max(12, current - 4), current]


def _device_item(device_code: str) -> dict:
    return next(item for item in DEMO_DEVICES if item["device_code"] == device_code)


def _alarm_name(alarm_code: str | None) -> str:
    return {
        "E101": "温度异常",
        "E201": "振动异常",
        "E203": "电机运行异常",
        "E302": "液压压力波动",
        "E404": "通信异常",
        "E501": "润滑异常",
    }.get(alarm_code or "", "设备异常")


def _cause_title(alarm_code: str | None) -> str:
    return {
        "E101": "散热能力下降或传感器读数异常",
        "E201": "机械连接异常或轴承磨损",
        "E203": "电机过载或控制器保护动作",
        "E302": "液压油路受阻或压力阀不稳定",
        "E404": "通信链路不稳定",
        "E501": "减速箱润滑不足或齿轮磨损",
    }.get(alarm_code or "", "设备运行状态异常")


def _cause_description(alarm_code: str | None) -> str:
    return {
        "E101": "报警与温度越限同时出现，可能由风道堵塞、负载过高或传感器异常引起。",
        "E201": "振动值超过安全阈值，可能与底座松动、联轴器不同心或轴承磨损有关。",
        "E203": "电机运行异常可能与过载、电流波动、控制器保护或机械阻力增大有关。",
        "E302": "液压压力波动可能与油位不足、滤芯堵塞、泵体磨损或阀组不稳定有关。",
        "E404": "通信异常可能影响状态采集连续性，需要检查连接链路和网关配置。",
        "E501": "温度与振动同步升高，可能指向润滑不足、油封泄漏或齿轮箱内部磨损。",
    }.get(alarm_code or "", "设备报警与运行参数异常同时存在，需要结合现场检查确认。")


def _verification(alarm_code: str | None) -> str:
    return {
        "E101": "检查散热风扇、通风口、滤网积尘和温度传感器读数。",
        "E201": "检查电机底座、联轴器同心度、轴承温度和负载端卡滞情况。",
        "E203": "检查电流、负载链路、控制器报警记录和驱动参数。",
        "E302": "检查液压油位、滤芯压差、泵体异响和压力调节阀状态。",
        "E404": "检查通信线缆、端子、网关、控制器日志和地址配置。",
        "E501": "检查减速箱油位、油色、漏油点、通气帽和轴承噪声。",
    }.get(alarm_code or "", "检查报警记录、运行参数和现场设备状态。")


def _action(alarm_code: str | None) -> str:
    return {
        "E101": "优先降低负载并清理散热通道，确认温度回落后再恢复运行。",
        "E201": "暂停高负载运行，紧固安装部件并复核轴承和联轴器状态。",
        "E203": "降低负载并检查控制器参数、接线和机械传动链路。",
        "E302": "检查油位和滤芯，必要时更换液压油并复核压力阀。",
        "E404": "固定通信线缆并检查网关、控制器和交换机日志。",
        "E501": "补充或更换润滑油，检查油封和齿轮箱温升，必要时停机拆检。",
    }.get(alarm_code or "", "安排现场巡检，确认异常来源并记录处理结果。")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = seed_demo_data(db)
        print(
            "Seeded enterprise demo data: "
            f"{result['created_devices']} devices, "
            f"{result['created_runtime_rows']} runtime rows, "
            f"{result['created_alarm_rows']} alarms, "
            f"{result['created_knowledge_documents']} knowledge documents, "
            f"{result['created_diagnosis_records']} diagnosis reports, "
            f"{result['created_risk_events']} risk events, "
            f"{result['created_maintenance_records']} maintenance records."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
