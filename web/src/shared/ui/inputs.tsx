"use client";

import {
    Form as AntdForm,
    Input as AntdInput,
    Select as AntdSelect,
    Switch as AntdSwitch,
    Upload as AntdUpload,
} from "antd";
import type { InputProps, SelectProps, SwitchProps } from "antd";
import type { TextAreaProps } from "antd/es/input";

/** 输入框：背景 raised、focus 环走 --s-* token（见 app-theme.ts）。 */
export function Input(props: InputProps) {
    return <AntdInput {...props} />;
}

/** 多行输入。 */
export function Textarea(props: TextAreaProps) {
    return <AntdInput.TextArea {...props} />;
}

/** 密码输入。 */
export function Password(props: InputProps) {
    return <AntdInput.Password {...props} />;
}

/** 选择器：浮层背景 overlay、选项高度 32（见 app-theme.ts）。 */
export function Select(props: SelectProps) {
    return <AntdSelect {...props} />;
}

/** 开关。 */
export function Switch(props: SwitchProps) {
    return <AntdSwitch {...props} />;
}

/** 上传：媒体素材入口。 */
export const Upload = AntdUpload;

/** 表单。 */
export const Form = AntdForm;
