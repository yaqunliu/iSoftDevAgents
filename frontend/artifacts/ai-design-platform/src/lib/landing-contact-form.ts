/**
 * 接口注释：
 * Contact 页表单的字段定义与校验。纯函数，不碰 DOM、不碰 React。
 *
 * 原因注释：
 * 校验逻辑抽出来单独放一个文件，是因为表单是整个官网最容易产生
 * "点了提交没反应" 这类静默失败的地方：某个字段校验条件写错，
 * 提交按钮就会永远进不去成功分支，而页面上不会有任何报错。
 * 抽成纯函数之后这些边界（空白字符串、只有空格、缺 @ 的邮箱、
 * 超长正文）都能直接用单测钉住，不需要把浏览器跑起来才能验。
 *
 * ⚠️ 这个表单目前不真正发送任何东西。见 submitContactEnquiry 的注释。
 */

export type ContactFormValues = {
  name: string;
  email: string;
  company: string;
  message: string;
};

/** 字段名。渲染顺序和校验顺序都以它为准。 */
export type ContactFieldName = keyof ContactFormValues;

export const CONTACT_FIELD_ORDER: ContactFieldName[] = ["name", "email", "company", "message"];

export const EMPTY_CONTACT_FORM: ContactFormValues = {
  name: "",
  email: "",
  company: "",
  message: "",
};

/**
 * 正文长度上限。
 *
 * 原因注释：设一个上限不是为了防攻击（这里根本没有后端），
 * 而是为了在接上真实后端之前，前端就已经和后端将来的字段长度对齐。
 * 等接口接上再补这条限制，就会出现"前端让填、后端存不下"的 500。
 */
export const CONTACT_MESSAGE_MAX_LENGTH = 2000;

/**
 * 校验错误。key 是字段名，value 是 i18n key 的后缀。
 *
 * 设计注释：这里返回 i18n key 后缀而不是拼好的英文句子。
 * 校验函数一旦开始返回人类可读文案，它就绑死了语言，
 * 将来加语言时错误提示会是整个页面唯一漏翻译的地方。
 */
export type ContactFormErrors = Partial<Record<ContactFieldName, string>>;

/**
 * 邮箱格式判断。
 *
 * 教学注释：
 * 这里刻意用一个宽松的判据（有且仅有一个 @、两侧非空、域名部分带点且点不在首尾），
 * 而不是网上流传的那种超长 RFC 5322 正则。
 * 原因是前端邮箱校验的目的只是拦住明显的手滑（漏了 @、写成 name@company），
 * 真正判定邮箱是否存在只能靠发一封信过去。
 * 用严格正则的代价是会误杀合法地址（比如带 + 号的、新顶级域的），
 * 而被误杀的用户没有任何补救手段，只能放弃咨询。宽松失败的代价远小于严格失败。
 */
export function isPlausibleEmail(value: string): boolean {
  const trimmed = value.trim();
  const parts = trimmed.split("@");
  if (parts.length !== 2) {
    return false;
  }
  const [local, domain] = parts;
  if (!local || !domain) {
    return false;
  }
  if (/\s/.test(trimmed)) {
    return false;
  }
  if (!domain.includes(".") || domain.startsWith(".") || domain.endsWith(".")) {
    return false;
  }
  return true;
}

/**
 * 校验整个表单。返回空对象表示通过。
 *
 * 设计注释：Company 是选填。企业站的联系表单里公司名看起来是必填，
 * 但真实场景中最有价值的来信常常来自还没成立公司的创始人、
 * 或者不方便透露雇主的技术负责人。把它设成必填只会把这批人挡在门外。
 */
export function validateContactForm(values: ContactFormValues): ContactFormErrors {
  const errors: ContactFormErrors = {};

  if (!values.name.trim()) {
    errors.name = "nameRequired";
  }

  const email = values.email.trim();
  if (!email) {
    errors.email = "emailRequired";
  } else if (!isPlausibleEmail(email)) {
    errors.email = "emailInvalid";
  }

  const message = values.message.trim();
  if (!message) {
    errors.message = "messageRequired";
  } else if (message.length > CONTACT_MESSAGE_MAX_LENGTH) {
    errors.message = "messageTooLong";
  }

  return errors;
}

export function hasContactFormErrors(errors: ContactFormErrors): boolean {
  return Object.keys(errors).length > 0;
}

/** 假提交模拟的耗时（毫秒）。 */
export const CONTACT_SUBMIT_DELAY_MS = 900;

/**
 * 提交咨询。
 *
 * ⚠️⚠️ 这个函数目前不发送任何东西。⚠️⚠️
 *
 * 它只是等待 CONTACT_SUBMIT_DELAY_MS 然后 resolve，让界面能走完
 * "提交中 → 成功" 的状态流转。填写的内容会随组件卸载一起丢掉，
 * 不会进任何收件箱、不会写任何数据库、也不会留下日志。
 *
 * 原因注释（给接后端的同事）：
 * 之所以先写成一个返回 Promise 的异步函数、而不是在组件里直接 setState 成功态，
 * 是为了让接真实接口时的改动收敛在这一个函数体内——
 * 把函数体换成 fetch("/api/contact", ...) 即可，组件的加载态、
 * 禁用态、错误态都已经按异步流程写好了，一行都不用动。
 *
 * 接上之前，页面上给访客的成功提示里附了真实邮箱 support@gmonkey.ai，
 * 这样即使这条消息实际丢了，访客手里仍然握着一条能真正送达的通路。
 * 那行字在接上真实后端之前不要删。
 */
export async function submitContactEnquiry(_values: ContactFormValues): Promise<void> {
  await new Promise<void>((resolve) => {
    setTimeout(resolve, CONTACT_SUBMIT_DELAY_MS);
  });
}
