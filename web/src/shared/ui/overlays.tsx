"use client";

import {
    Drawer as AntdDrawer,
    Dropdown as AntdDropdown,
    Modal as AntdModal,
    Popconfirm as AntdPopconfirm,
    Popover as AntdPopover,
    Tooltip as AntdTooltip,
} from "antd";
import type { DrawerProps, DropdownProps, ModalProps, PopconfirmProps, PopoverProps, TooltipProps } from "antd";

/** 模态：圆角 lg、头部无分隔线、遮罩在 app-theme.ts 统一。 */
export function Modal(props: ModalProps) {
    return <AntdModal {...props} />;
}

/** 抽屉。 */
export function Drawer(props: DrawerProps) {
    return <AntdDrawer {...props} />;
}

/** 气泡提示：overlay 底、延迟 400ms。 */
export function Tooltip(props: TooltipProps) {
    return <AntdTooltip mouseEnterDelay={0.4} {...props} />;
}

/** 二次确认。 */
export function Popconfirm(props: PopconfirmProps) {
    return <AntdPopconfirm {...props} />;
}

/** 气泡卡片。 */
export function Popover(props: PopoverProps) {
    return <AntdPopover {...props} />;
}

/** 下拉菜单。 */
export function Dropdown(props: DropdownProps) {
    return <AntdDropdown {...props} />;
}

export type { MenuProps } from "antd";
