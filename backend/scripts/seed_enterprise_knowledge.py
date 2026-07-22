"""Seed enterprise-grade structured fault knowledge.

This script is idempotent and uses the configured DATABASE_URL. It does not
delete existing documents, chunks, or vector records.
"""

from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import select


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.knowledge_structured import (  # noqa: E402
    FaultCause,
    FaultKnowledgeEntry,
    InspectionStep,
    MaintenanceAction,
    MaintenanceCase,
)


ENTERPRISE_FAULTS = [
    {
        "fault_code": "E101",
        "fault_name": "温度异常",
        "description": "设备或传感器温度超过安全运行范围。",
        "severity": "high",
        "device_type": "sensor",
        "model": "Temperature Sensor C",
        "trigger_conditions": {
            "temperature": ">60℃",
            "trend": "持续升温",
        },
        "causes": [
            ("散热通道堵塞", 1, "温度持续升高且设备负载未明显变化", "检查风扇、滤网和通风口"),
            ("温度传感器漂移", 2, "现场体感温度与采集值不一致", "使用独立测温设备复核"),
            ("设备负载偏高", 3, "温度与电流同步升高", "核对负载和电流趋势"),
        ],
        "steps": [
            (1, "检查温度实时值和 30 分钟趋势", "确认是否持续超过阈值", "避免接触高温部件"),
            (2, "检查散热风扇、滤网和通风口", "散热路径无堵塞", "佩戴防护手套"),
            (3, "复核传感器读数", "独立测温结果与系统读数一致", "按电气安全规程操作"),
        ],
        "actions": [
            (1, "温度继续上升时降低负载或安全停机", "温度超过安全范围"),
            (2, "清理散热通道并恢复通风", "发现堵塞或风扇异常"),
            (3, "更换或重新校准温度传感器", "读数与现场复核不一致"),
        ],
        "cases": [
            ("Workshop C", "E101", "温度持续高于 60℃", "滤网堵塞", "清理滤网并复测", "温度恢复正常"),
            ("Temperature Sensor C", "E101", "温度读数跳变", "传感器漂移", "更换传感器", "报警解除"),
        ],
    },
    {
        "fault_code": "E201",
        "fault_name": "振动异常",
        "description": "设备振动值超过允许范围，可能引发机械损坏。",
        "severity": "high",
        "device_type": "motor",
        "model": "Vibration Motor E",
        "trigger_conditions": {"vibration": ">0.4mm/s"},
        "causes": [
            ("轴承磨损", 1, "振动升高并伴随异响", "检查轴承温度、润滑和间隙"),
            ("机械连接松动", 2, "振动在负载变化时波动", "检查地脚螺栓和联轴器"),
            ("转轴对中不良", 3, "振动方向性明显", "执行对中检查"),
        ],
        "steps": [
            (1, "确认振动传感器安装状态", "传感器固定可靠", "设备运转区域保持警戒"),
            (2, "检查地脚螺栓和联轴器", "无松动、偏心或裂纹", "停机挂牌后检查"),
            (3, "检查轴承润滑和磨损", "轴承无过热和异常间隙", "防止机械夹伤"),
        ],
        "actions": [
            (1, "降低负载并观察振动变化", "振动接近或超过阈值"),
            (2, "紧固机械连接件并复测振动", "发现连接松动"),
            (3, "更换磨损轴承或重新对中", "确认轴承或对中异常"),
        ],
        "cases": [
            ("DEV-005", "E201", "振动值 0.62mm/s", "联轴器螺栓松动", "紧固并复测", "振动恢复正常"),
            ("Motor Line E", "E201", "振动长期接近阈值", "轴承润滑不足", "补充润滑并更换轴承", "设备稳定运行"),
        ],
    },
    {
        "fault_code": "E203",
        "fault_name": "电机运行异常",
        "description": "电机运行状态异常，常见于过载、驱动异常或机械阻力升高。",
        "severity": "medium",
        "device_type": "motor",
        "model": "Motor Drive B",
        "trigger_conditions": {"current": ">8A", "runtime": "电流或振动异常"},
        "causes": [
            ("机械负载过大", 1, "电流偏高且温度上升", "检查负载端是否卡滞"),
            ("传动部件异常", 2, "电流和振动同步升高", "检查联轴器、皮带和轴承"),
            ("驱动参数不合理", 3, "控制器日志存在保护动作", "核对驱动参数和报警日志"),
        ],
        "steps": [
            (1, "检查电流、电压、温度和振动", "参数处于安全范围", "注意电气安全"),
            (2, "检查负载端机械阻力", "无卡滞或异常摩擦", "停机后检查传动部件"),
            (3, "查看控制器报警日志", "确认保护动作原因", "由电气工程师执行"),
        ],
        "actions": [
            (1, "降低负载并观察电流变化", "电流持续偏高"),
            (2, "检修负载端传动结构", "发现机械阻力异常"),
            (3, "复核驱动器参数", "控制器保护频繁触发"),
        ],
        "cases": [
            ("Motor Drive B", "E203", "电流高于正常值", "传动阻力增大", "润滑维护", "电流恢复"),
            ("Motor Line B", "E203", "振动与电流同步升高", "联轴器偏心", "重新对中", "报警解除"),
        ],
    },
    {
        "fault_code": "E404",
        "fault_name": "通信异常",
        "description": "设备通信链路异常，导致状态或运行数据无法稳定上报。",
        "severity": "medium",
        "device_type": "communication",
        "model": "Industrial Gateway",
        "trigger_conditions": {"network": "timeout", "data": "无数据上报"},
        "causes": [
            ("通信线缆松动", 1, "设备间歇性离线", "检查端子、网线和指示灯"),
            ("网络配置错误", 2, "网关日志出现地址或端口错误", "核对 IP、端口和协议"),
            ("通信模块异常", 3, "重启后短暂恢复", "检查控制器通信模块日志"),
        ],
        "steps": [
            (1, "检查最后上报时间和在线状态", "确认异常发生时间", "不得绕过联锁逻辑"),
            (2, "检查网线、端子和交换机端口", "物理连接可靠", "按电气安全规程操作"),
            (3, "核对网络和协议配置", "配置与系统台账一致", "由授权人员修改配置"),
        ],
        "actions": [
            (1, "恢复物理连接并重新建立通信", "发现线缆或端子松动"),
            (2, "修正网络配置并重启通信服务", "配置错误"),
            (3, "更换通信模块或网关", "模块故障确认"),
        ],
        "cases": [
            ("DEV-002", "E404", "通信间歇中断", "网关端口松动", "重新压接端子", "通信恢复"),
            ("Sensor Network", "E404", "多个传感器同时离线", "交换机地址冲突", "调整网络配置", "数据恢复"),
        ],
    },
]


def main() -> None:
    db = SessionLocal()
    inserted = 0
    try:
        for fault in ENTERPRISE_FAULTS:
            existing = db.scalar(
                select(FaultKnowledgeEntry).where(
                    FaultKnowledgeEntry.fault_code == fault["fault_code"]
                )
            )
            if existing is not None:
                continue

            entry = FaultKnowledgeEntry(
                fault_code=fault["fault_code"],
                fault_name=fault["fault_name"],
                description=fault["description"],
                severity=fault["severity"],
                device_type=fault["device_type"],
                model=fault["model"],
                trigger_conditions=fault["trigger_conditions"],
            )
            db.add(entry)
            db.flush()

            for cause, priority, evidence, verification in fault["causes"]:
                db.add(
                    FaultCause(
                        fault_entry_id=entry.id,
                        cause=cause,
                        priority=priority,
                        evidence=evidence,
                        verification_method=verification,
                    )
                )

            for order, operation, expected_result, safety_requirement in fault["steps"]:
                db.add(
                    InspectionStep(
                        fault_entry_id=entry.id,
                        order=order,
                        operation=operation,
                        expected_result=expected_result,
                        safety_requirement=safety_requirement,
                    )
                )

            for priority, action, condition in fault["actions"]:
                db.add(
                    MaintenanceAction(
                        fault_entry_id=entry.id,
                        priority=priority,
                        action=action,
                        condition=condition,
                    )
                )

            for device, fault_code, symptom, root_cause, solution, result in fault["cases"]:
                db.add(
                    MaintenanceCase(
                        fault_entry_id=entry.id,
                        device=device,
                        fault=fault_code,
                        symptom=symptom,
                        root_cause=root_cause,
                        solution=solution,
                        result=result,
                    )
                )
            inserted += 1

        db.commit()
        print(f"Inserted structured fault entries: {inserted}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
