# 同一订单、同一问题只允许一个活跃申请；调用方必须持有审核运行锁。
from sqlalchemy import select
from app.db.models import Ticket


class DuplicateApplication(ValueError):
    pass


def check_application(graph, session, proposal, *, own_approval_id=None):
    order_id, issue = proposal['order_id'], proposal['issue_type']
    tickets = session.scalars(select(Ticket).where(Ticket.order_id == order_id, Ticket.issue_type == issue)).all()
    active = next((t for t in tickets if t.status != 'closed'), None)
    if active:
        raise DuplicateApplication(f'该订单已有未关闭的同类工单 {active.ticket_id}，请处理已有工单，勿重复申请。')
    closed = {t.approval_id for t in tickets if t.status == 'closed'}
    # SqliteSaver 枚举持有游标锁，必须先完全消费，再逐个读取最新状态。
    snapshots = list(graph.checkpointer.list(None))
    ids = {s.config['configurable']['thread_id'] for s in snapshots}
    for approval_id in ids - closed:
        if approval_id == own_approval_id:
            continue
        saved = graph.get_state({'configurable': {'thread_id': approval_id}}).values
        previous = saved.get('proposal', {})
        if previous.get('order_id') == order_id and previous.get('issue_type') == issue and previous.get('approval_status') in {'pending', 'approved'}:
            raise DuplicateApplication('该订单已有待审核或已批准待执行的同类申请，请等待已有申请处理，勿重复提交。')
