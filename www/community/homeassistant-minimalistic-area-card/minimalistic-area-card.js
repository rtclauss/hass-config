var t,e,i=function(t,e){return s(e).format(t)},s=function(t){return new Intl.DateTimeFormat(t.language,{year:"numeric",month:"long",day:"numeric"})};!function(t){t.language="language",t.system="system",t.comma_decimal="comma_decimal",t.decimal_comma="decimal_comma",t.space_comma="space_comma",t.none="none"}(t||(t={})),function(t){t.language="language",t.system="system",t.am_pm="12",t.twenty_four="24"}(e||(e={}));var n=function(t){if(t.time_format===e.language||t.time_format===e.system){var i=t.time_format===e.language?t.language:void 0,s=(new Date).toLocaleString(i);return s.includes("AM")||s.includes("PM")}return t.time_format===e.am_pm},o=function(t,e){return r(e).format(t)},r=function(t){return new Intl.DateTimeFormat(t.language,{year:"numeric",month:"long",day:"numeric",hour:n(t)?"numeric":"2-digit",minute:"2-digit",hour12:n(t)})},a=function(t,e){return h(e).format(t)},h=function(t){return new Intl.DateTimeFormat(t.language,{hour:"numeric",minute:"2-digit",hour12:n(t)})};function c(){return(c=Object.assign||function(t){for(var e=1;e<arguments.length;e++){var i=arguments[e];for(var s in i)Object.prototype.hasOwnProperty.call(i,s)&&(t[s]=i[s])}return t}).apply(this,arguments)}function l(t){return t.substr(0,t.indexOf("."))}var d=function(e){switch(e.number_format){case t.comma_decimal:return["en-US","en"];case t.decimal_comma:return["de","es","it"];case t.space_comma:return["fr","sv","cs"];case t.system:return;default:return e.language}},u=function(t,e){return void 0===e&&(e=2),Math.round(t*Math.pow(10,e))/Math.pow(10,e)},p=function(e,i,s){var n=i?d(i):void 0;if(Number.isNaN=Number.isNaN||function t(e){return"number"==typeof e&&t(e)},(null==i?void 0:i.number_format)!==t.none&&!Number.isNaN(Number(e))&&Intl)try{return new Intl.NumberFormat(n,m(e,s)).format(Number(e))}catch(t){return console.error(t),new Intl.NumberFormat(void 0,m(e,s)).format(Number(e))}return"string"==typeof e?e:u(e,null==s?void 0:s.maximumFractionDigits).toString()+("currency"===(null==s?void 0:s.style)?" "+s.currency:"")},m=function(t,e){var i=c({maximumFractionDigits:2},e);if("string"!=typeof t)return i;if(!e||!e.minimumFractionDigits&&!e.maximumFractionDigits){var s=t.indexOf(".")>-1?t.split(".")[1].length:0;i.minimumFractionDigits=s,i.maximumFractionDigits=s}return i},g=function(t,e,s,n){var r=void 0!==n?n:e.state;if("unknown"===r||"unavailable"===r)return t("state.default."+r);if(function(t){return!!t.attributes.unit_of_measurement||!!t.attributes.state_class}(e)){if("monetary"===e.attributes.device_class)try{return p(r,s,{style:"currency",currency:e.attributes.unit_of_measurement})}catch(t){}return p(r,s)+(e.attributes.unit_of_measurement?" "+e.attributes.unit_of_measurement:"")}var h=function(t){return l(t.entity_id)}(e);if("input_datetime"===h){var c;if(void 0===n)return e.attributes.has_date&&e.attributes.has_time?(c=new Date(e.attributes.year,e.attributes.month-1,e.attributes.day,e.attributes.hour,e.attributes.minute),o(c,s)):e.attributes.has_date?(c=new Date(e.attributes.year,e.attributes.month-1,e.attributes.day),i(c,s)):e.attributes.has_time?((c=new Date).setHours(e.attributes.hour,e.attributes.minute),a(c,s)):e.state;try{var d=n.split(" ");if(2===d.length)return o(new Date(d.join("T")),s);if(1===d.length){if(n.includes("-"))return i(new Date(n+"T00:00"),s);if(n.includes(":")){var u=new Date;return a(new Date(u.toISOString().split("T")[0]+"T"+n),s)}}return n}catch(t){return n}}return"humidifier"===h&&"on"===r&&e.attributes.humidity?e.attributes.humidity+" %":"counter"===h||"number"===h||"input_number"===h?p(r,s):e.attributes.device_class&&t("component."+h+".state."+e.attributes.device_class+"."+r)||t("component."+h+".state._."+r)||r},_=["closed","locked","off"],f=function(t,e,i,s){s=s||{},i=null==i?{}:i;var n=new Event(e,{bubbles:void 0===s.bubbles||s.bubbles,cancelable:Boolean(s.cancelable),composed:void 0===s.composed||s.composed});return n.detail=i,t.dispatchEvent(n),n},$=function(t){f(window,"haptic",t)},v=function(t,e){return function(t,e,i){void 0===i&&(i=!0);var s,n=l(e),o="group"===n?"homeassistant":n;switch(n){case"lock":s=i?"unlock":"lock";break;case"cover":s=i?"open_cover":"close_cover";break;default:s=i?"turn_on":"turn_off"}return t.callService(o,s,{entity_id:e})}(t,e,_.includes(t.states[e].state))},b=function(t,e,i,s){if(s||(s={action:"more-info"}),!s.confirmation||s.confirmation.exemptions&&s.confirmation.exemptions.some((function(t){return t.user===e.user.id}))||($("warning"),confirm(s.confirmation.text||"Are you sure you want to "+s.action+"?")))switch(s.action){case"more-info":(i.entity||i.camera_image)&&f(t,"hass-more-info",{entityId:i.entity?i.entity:i.camera_image});break;case"navigate":s.navigation_path&&function(t,e,i){void 0===i&&(i=!1),i?history.replaceState(null,"",e):history.pushState(null,"",e),f(window,"location-changed",{replace:i})}(0,s.navigation_path);break;case"url":s.url_path&&window.open(s.url_path);break;case"toggle":i.entity&&(v(e,i.entity),$("success"));break;case"call-service":if(!s.service)return void $("failure");var n=s.service.split(".",2);e.callService(n[0],n[1],s.service_data,s.target),$("success");break;case"fire-dom-event":f(t,"ll-custom",s)}},y=function(t,e,i,s){var n;"double_tap"===s&&i.double_tap_action?n=i.double_tap_action:"hold"===s&&i.hold_action?n=i.hold_action:"tap"===s&&i.tap_action&&(n=i.tap_action),b(t,e,i,n)};function A(t){return void 0!==t&&"none"!==t.action}
/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const w=globalThis,x=w.ShadowRoot&&(void 0===w.ShadyCSS||w.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,E=Symbol(),S=new WeakMap;class N{constructor(t,e,i){if(this._$cssResult$=!0,i!==E)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const e=this.t;if(x&&void 0===t){const i=void 0!==e&&1===e.length;i&&(t=S.get(e)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),i&&S.set(e,t))}return t}toString(){return this.cssText}}const C=(t,...e)=>{const i=1===t.length?t[0]:e.reduce(((e,i,s)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+t[s+1]),t[0]);return new N(i,t,E)},T=x?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const i of t.cssRules)e+=i.cssText;return(t=>new N("string"==typeof t?t:t+"",void 0,E))(e)})(t):t
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */,{is:k,defineProperty:H,getOwnPropertyDescriptor:U,getOwnPropertyNames:P,getOwnPropertySymbols:D,getPrototypeOf:O}=Object,M=globalThis,I=M.trustedTypes,R=I?I.emptyScript:"",j=M.reactiveElementPolyfillSupport,L=(t,e)=>t,z={toAttribute(t,e){switch(e){case Boolean:t=t?R:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let i=t;switch(e){case Boolean:i=null!==t;break;case Number:i=null===t?null:Number(t);break;case Object:case Array:try{i=JSON.parse(t)}catch(t){i=null}}return i}},F=(t,e)=>!k(t,e),B={attribute:!0,type:String,converter:z,reflect:!1,hasChanged:F};Symbol.metadata??=Symbol("metadata"),M.litPropertyMetadata??=new WeakMap;class V extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=B){if(e.state&&(e.attribute=!1),this._$Ei(),this.elementProperties.set(t,e),!e.noAccessor){const i=Symbol(),s=this.getPropertyDescriptor(t,i,e);void 0!==s&&H(this.prototype,t,s)}}static getPropertyDescriptor(t,e,i){const{get:s,set:n}=U(this.prototype,t)??{get(){return this[e]},set(t){this[e]=t}};return{get(){return s?.call(this)},set(e){const o=s?.call(this);n.call(this,e),this.requestUpdate(t,o,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??B}static _$Ei(){if(this.hasOwnProperty(L("elementProperties")))return;const t=O(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(L("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(L("properties"))){const t=this.properties,e=[...P(t),...D(t)];for(const i of e)this.createProperty(i,t[i])}const t=this[Symbol.metadata];if(null!==t){const e=litPropertyMetadata.get(t);if(void 0!==e)for(const[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(const[t,e]of this.elementProperties){const i=this._$Eu(t,e);void 0!==i&&this._$Eh.set(i,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const i=new Set(t.flat(1/0).reverse());for(const t of i)e.unshift(T(t))}else void 0!==t&&e.push(T(t));return e}static _$Eu(t,e){const i=e.attribute;return!1===i?void 0:"string"==typeof i?i:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise((t=>this.enableUpdating=t)),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach((t=>t(this)))}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){const t=new Map,e=this.constructor.elementProperties;for(const i of e.keys())this.hasOwnProperty(i)&&(t.set(i,this[i]),delete this[i]);t.size>0&&(this._$Ep=t)}createRenderRoot(){const t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((t,e)=>{if(x)t.adoptedStyleSheets=e.map((t=>t instanceof CSSStyleSheet?t:t.styleSheet));else for(const i of e){const e=document.createElement("style"),s=w.litNonce;void 0!==s&&e.setAttribute("nonce",s),e.textContent=i.cssText,t.appendChild(e)}})(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach((t=>t.hostConnected?.()))}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach((t=>t.hostDisconnected?.()))}attributeChangedCallback(t,e,i){this._$AK(t,i)}_$EC(t,e){const i=this.constructor.elementProperties.get(t),s=this.constructor._$Eu(t,i);if(void 0!==s&&!0===i.reflect){const n=(void 0!==i.converter?.toAttribute?i.converter:z).toAttribute(e,i.type);this._$Em=t,null==n?this.removeAttribute(s):this.setAttribute(s,n),this._$Em=null}}_$AK(t,e){const i=this.constructor,s=i._$Eh.get(t);if(void 0!==s&&this._$Em!==s){const t=i.getPropertyOptions(s),n="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:z;this._$Em=s,this[s]=n.fromAttribute(e,t.type),this._$Em=null}}requestUpdate(t,e,i){if(void 0!==t){if(i??=this.constructor.getPropertyOptions(t),!(i.hasChanged??F)(this[t],e))return;this.P(t,e,i)}!1===this.isUpdatePending&&(this._$ES=this._$ET())}P(t,e,i){this._$AL.has(t)||this._$AL.set(t,e),!0===i.reflect&&this._$Em!==t&&(this._$Ej??=new Set).add(t)}async _$ET(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,e]of this._$Ep)this[t]=e;this._$Ep=void 0}const t=this.constructor.elementProperties;if(t.size>0)for(const[e,i]of t)!0!==i.wrapped||this._$AL.has(e)||void 0===this[e]||this.P(e,this[e],i)}let t=!1;const e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach((t=>t.hostUpdate?.())),this.update(e)):this._$EU()}catch(e){throw t=!1,this._$EU(),e}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach((t=>t.hostUpdated?.())),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EU(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Ej&&=this._$Ej.forEach((t=>this._$EC(t,this[t]))),this._$EU()}updated(t){}firstUpdated(t){}}V.elementStyles=[],V.shadowRootOptions={mode:"open"},V[L("elementProperties")]=new Map,V[L("finalized")]=new Map,j?.({ReactiveElement:V}),(M.reactiveElementVersions??=[]).push("2.0.4");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const W=globalThis,q=W.trustedTypes,Z=q?q.createPolicy("lit-html",{createHTML:t=>t}):void 0,K="$lit$",Y=`lit$${Math.random().toFixed(9).slice(2)}$`,J="?"+Y,X=`<${J}>`,G=document,Q=()=>G.createComment(""),tt=t=>null===t||"object"!=typeof t&&"function"!=typeof t,et=Array.isArray,it="[ \t\n\f\r]",st=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,nt=/-->/g,ot=/>/g,rt=RegExp(`>|${it}(?:([^\\s"'>=/]+)(${it}*=${it}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),at=/'/g,ht=/"/g,ct=/^(?:script|style|textarea|title)$/i,lt=Symbol.for("lit-noChange"),dt=Symbol.for("lit-nothing"),ut=new WeakMap,pt=G.createTreeWalker(G,129);function mt(t,e){if(!Array.isArray(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==Z?Z.createHTML(e):e}class gt{constructor({strings:t,_$litType$:e},i){let s;this.parts=[];let n=0,o=0;const r=t.length-1,a=this.parts,[h,c]=((t,e)=>{const i=t.length-1,s=[];let n,o=2===e?"<svg>":"",r=st;for(let e=0;e<i;e++){const i=t[e];let a,h,c=-1,l=0;for(;l<i.length&&(r.lastIndex=l,h=r.exec(i),null!==h);)l=r.lastIndex,r===st?"!--"===h[1]?r=nt:void 0!==h[1]?r=ot:void 0!==h[2]?(ct.test(h[2])&&(n=RegExp("</"+h[2],"g")),r=rt):void 0!==h[3]&&(r=rt):r===rt?">"===h[0]?(r=n??st,c=-1):void 0===h[1]?c=-2:(c=r.lastIndex-h[2].length,a=h[1],r=void 0===h[3]?rt:'"'===h[3]?ht:at):r===ht||r===at?r=rt:r===nt||r===ot?r=st:(r=rt,n=void 0);const d=r===rt&&t[e+1].startsWith("/>")?" ":"";o+=r===st?i+X:c>=0?(s.push(a),i.slice(0,c)+K+i.slice(c)+Y+d):i+Y+(-2===c?e:d)}return[mt(t,o+(t[i]||"<?>")+(2===e?"</svg>":"")),s]})(t,e);if(this.el=gt.createElement(h,i),pt.currentNode=this.el.content,2===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(s=pt.nextNode())&&a.length<r;){if(1===s.nodeType){if(s.hasAttributes())for(const t of s.getAttributeNames())if(t.endsWith(K)){const e=c[o++],i=s.getAttribute(t).split(Y),r=/([.?@])?(.*)/.exec(e);a.push({type:1,index:n,name:r[2],strings:i,ctor:"."===r[1]?bt:"?"===r[1]?yt:"@"===r[1]?At:vt}),s.removeAttribute(t)}else t.startsWith(Y)&&(a.push({type:6,index:n}),s.removeAttribute(t));if(ct.test(s.tagName)){const t=s.textContent.split(Y),e=t.length-1;if(e>0){s.textContent=q?q.emptyScript:"";for(let i=0;i<e;i++)s.append(t[i],Q()),pt.nextNode(),a.push({type:2,index:++n});s.append(t[e],Q())}}}else if(8===s.nodeType)if(s.data===J)a.push({type:2,index:n});else{let t=-1;for(;-1!==(t=s.data.indexOf(Y,t+1));)a.push({type:7,index:n}),t+=Y.length-1}n++}}static createElement(t,e){const i=G.createElement("template");return i.innerHTML=t,i}}function _t(t,e,i=t,s){if(e===lt)return e;let n=void 0!==s?i._$Co?.[s]:i._$Cl;const o=tt(e)?void 0:e._$litDirective$;return n?.constructor!==o&&(n?._$AO?.(!1),void 0===o?n=void 0:(n=new o(t),n._$AT(t,i,s)),void 0!==s?(i._$Co??=[])[s]=n:i._$Cl=n),void 0!==n&&(e=_t(t,n._$AS(t,e.values),n,s)),e}class ft{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:i}=this._$AD,s=(t?.creationScope??G).importNode(e,!0);pt.currentNode=s;let n=pt.nextNode(),o=0,r=0,a=i[0];for(;void 0!==a;){if(o===a.index){let e;2===a.type?e=new $t(n,n.nextSibling,this,t):1===a.type?e=new a.ctor(n,a.name,a.strings,this,t):6===a.type&&(e=new wt(n,this,t)),this._$AV.push(e),a=i[++r]}o!==a?.index&&(n=pt.nextNode(),o++)}return pt.currentNode=G,s}p(t){let e=0;for(const i of this._$AV)void 0!==i&&(void 0!==i.strings?(i._$AI(t,i,e),e+=i.strings.length-2):i._$AI(t[e])),e++}}class $t{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,i,s){this.type=2,this._$AH=dt,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=i,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=_t(this,t,e),tt(t)?t===dt||null==t||""===t?(this._$AH!==dt&&this._$AR(),this._$AH=dt):t!==this._$AH&&t!==lt&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>et(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}S(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.S(t))}_(t){this._$AH!==dt&&tt(this._$AH)?this._$AA.nextSibling.data=t:this.T(G.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:i}=t,s="number"==typeof i?this._$AC(t):(void 0===i.el&&(i.el=gt.createElement(mt(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===s)this._$AH.p(e);else{const t=new ft(s,this),i=t.u(this.options);t.p(e),this.T(i),this._$AH=t}}_$AC(t){let e=ut.get(t.strings);return void 0===e&&ut.set(t.strings,e=new gt(t)),e}k(t){et(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let i,s=0;for(const n of t)s===e.length?e.push(i=new $t(this.S(Q()),this.S(Q()),this,this.options)):i=e[s],i._$AI(n),s++;s<e.length&&(this._$AR(i&&i._$AB.nextSibling,s),e.length=s)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t&&t!==this._$AB;){const e=t.nextSibling;t.remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class vt{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,i,s,n){this.type=1,this._$AH=dt,this._$AN=void 0,this.element=t,this.name=e,this._$AM=s,this.options=n,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=dt}_$AI(t,e=this,i,s){const n=this.strings;let o=!1;if(void 0===n)t=_t(this,t,e,0),o=!tt(t)||t!==this._$AH&&t!==lt,o&&(this._$AH=t);else{const s=t;let r,a;for(t=n[0],r=0;r<n.length-1;r++)a=_t(this,s[i+r],e,r),a===lt&&(a=this._$AH[r]),o||=!tt(a)||a!==this._$AH[r],a===dt?t=dt:t!==dt&&(t+=(a??"")+n[r+1]),this._$AH[r]=a}o&&!s&&this.j(t)}j(t){t===dt?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class bt extends vt{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===dt?void 0:t}}class yt extends vt{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==dt)}}class At extends vt{constructor(t,e,i,s,n){super(t,e,i,s,n),this.type=5}_$AI(t,e=this){if((t=_t(this,t,e,0)??dt)===lt)return;const i=this._$AH,s=t===dt&&i!==dt||t.capture!==i.capture||t.once!==i.once||t.passive!==i.passive,n=t!==dt&&(i===dt||s);s&&this.element.removeEventListener(this.name,this,i),n&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class wt{constructor(t,e,i){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(t){_t(this,t)}}const xt=W.litHtmlPolyfillSupport;xt?.(gt,$t),(W.litHtmlVersions??=[]).push("3.1.3");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const Et=globalThis,St=Et.trustedTypes,Nt=St?St.createPolicy("lit-html",{createHTML:t=>t}):void 0,Ct="$lit$",Tt=`lit$${Math.random().toFixed(9).slice(2)}$`,kt="?"+Tt,Ht=`<${kt}>`,Ut=document,Pt=()=>Ut.createComment(""),Dt=t=>null===t||"object"!=typeof t&&"function"!=typeof t,Ot=Array.isArray,Mt="[ \t\n\f\r]",It=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Rt=/-->/g,jt=/>/g,Lt=RegExp(`>|${Mt}(?:([^\\s"'>=/]+)(${Mt}*=${Mt}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),zt=/'/g,Ft=/"/g,Bt=/^(?:script|style|textarea|title)$/i,Vt=(t=>(e,...i)=>({_$litType$:t,strings:e,values:i}))(1),Wt=Symbol.for("lit-noChange"),qt=Symbol.for("lit-nothing"),Zt=new WeakMap,Kt=Ut.createTreeWalker(Ut,129);function Yt(t,e){if(!Array.isArray(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==Nt?Nt.createHTML(e):e}const Jt=(t,e)=>{const i=t.length-1,s=[];let n,o=2===e?"<svg>":"",r=It;for(let e=0;e<i;e++){const i=t[e];let a,h,c=-1,l=0;for(;l<i.length&&(r.lastIndex=l,h=r.exec(i),null!==h);)l=r.lastIndex,r===It?"!--"===h[1]?r=Rt:void 0!==h[1]?r=jt:void 0!==h[2]?(Bt.test(h[2])&&(n=RegExp("</"+h[2],"g")),r=Lt):void 0!==h[3]&&(r=Lt):r===Lt?">"===h[0]?(r=n??It,c=-1):void 0===h[1]?c=-2:(c=r.lastIndex-h[2].length,a=h[1],r=void 0===h[3]?Lt:'"'===h[3]?Ft:zt):r===Ft||r===zt?r=Lt:r===Rt||r===jt?r=It:(r=Lt,n=void 0);const d=r===Lt&&t[e+1].startsWith("/>")?" ":"";o+=r===It?i+Ht:c>=0?(s.push(a),i.slice(0,c)+Ct+i.slice(c)+Tt+d):i+Tt+(-2===c?e:d)}return[Yt(t,o+(t[i]||"<?>")+(2===e?"</svg>":"")),s]};class Xt{constructor({strings:t,_$litType$:e},i){let s;this.parts=[];let n=0,o=0;const r=t.length-1,a=this.parts,[h,c]=Jt(t,e);if(this.el=Xt.createElement(h,i),Kt.currentNode=this.el.content,2===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(s=Kt.nextNode())&&a.length<r;){if(1===s.nodeType){if(s.hasAttributes())for(const t of s.getAttributeNames())if(t.endsWith(Ct)){const e=c[o++],i=s.getAttribute(t).split(Tt),r=/([.?@])?(.*)/.exec(e);a.push({type:1,index:n,name:r[2],strings:i,ctor:"."===r[1]?ie:"?"===r[1]?se:"@"===r[1]?ne:ee}),s.removeAttribute(t)}else t.startsWith(Tt)&&(a.push({type:6,index:n}),s.removeAttribute(t));if(Bt.test(s.tagName)){const t=s.textContent.split(Tt),e=t.length-1;if(e>0){s.textContent=St?St.emptyScript:"";for(let i=0;i<e;i++)s.append(t[i],Pt()),Kt.nextNode(),a.push({type:2,index:++n});s.append(t[e],Pt())}}}else if(8===s.nodeType)if(s.data===kt)a.push({type:2,index:n});else{let t=-1;for(;-1!==(t=s.data.indexOf(Tt,t+1));)a.push({type:7,index:n}),t+=Tt.length-1}n++}}static createElement(t,e){const i=Ut.createElement("template");return i.innerHTML=t,i}}function Gt(t,e,i=t,s){if(e===Wt)return e;let n=void 0!==s?i._$Co?.[s]:i._$Cl;const o=Dt(e)?void 0:e._$litDirective$;return n?.constructor!==o&&(n?._$AO?.(!1),void 0===o?n=void 0:(n=new o(t),n._$AT(t,i,s)),void 0!==s?(i._$Co??=[])[s]=n:i._$Cl=n),void 0!==n&&(e=Gt(t,n._$AS(t,e.values),n,s)),e}class Qt{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:i}=this._$AD,s=(t?.creationScope??Ut).importNode(e,!0);Kt.currentNode=s;let n=Kt.nextNode(),o=0,r=0,a=i[0];for(;void 0!==a;){if(o===a.index){let e;2===a.type?e=new te(n,n.nextSibling,this,t):1===a.type?e=new a.ctor(n,a.name,a.strings,this,t):6===a.type&&(e=new oe(n,this,t)),this._$AV.push(e),a=i[++r]}o!==a?.index&&(n=Kt.nextNode(),o++)}return Kt.currentNode=Ut,s}p(t){let e=0;for(const i of this._$AV)void 0!==i&&(void 0!==i.strings?(i._$AI(t,i,e),e+=i.strings.length-2):i._$AI(t[e])),e++}}class te{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,i,s){this.type=2,this._$AH=qt,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=i,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=Gt(this,t,e),Dt(t)?t===qt||null==t||""===t?(this._$AH!==qt&&this._$AR(),this._$AH=qt):t!==this._$AH&&t!==Wt&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>Ot(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}S(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.S(t))}_(t){this._$AH!==qt&&Dt(this._$AH)?this._$AA.nextSibling.data=t:this.T(Ut.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:i}=t,s="number"==typeof i?this._$AC(t):(void 0===i.el&&(i.el=Xt.createElement(Yt(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===s)this._$AH.p(e);else{const t=new Qt(s,this),i=t.u(this.options);t.p(e),this.T(i),this._$AH=t}}_$AC(t){let e=Zt.get(t.strings);return void 0===e&&Zt.set(t.strings,e=new Xt(t)),e}k(t){Ot(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let i,s=0;for(const n of t)s===e.length?e.push(i=new te(this.S(Pt()),this.S(Pt()),this,this.options)):i=e[s],i._$AI(n),s++;s<e.length&&(this._$AR(i&&i._$AB.nextSibling,s),e.length=s)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t&&t!==this._$AB;){const e=t.nextSibling;t.remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class ee{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,i,s,n){this.type=1,this._$AH=qt,this._$AN=void 0,this.element=t,this.name=e,this._$AM=s,this.options=n,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=qt}_$AI(t,e=this,i,s){const n=this.strings;let o=!1;if(void 0===n)t=Gt(this,t,e,0),o=!Dt(t)||t!==this._$AH&&t!==Wt,o&&(this._$AH=t);else{const s=t;let r,a;for(t=n[0],r=0;r<n.length-1;r++)a=Gt(this,s[i+r],e,r),a===Wt&&(a=this._$AH[r]),o||=!Dt(a)||a!==this._$AH[r],a===qt?t=qt:t!==qt&&(t+=(a??"")+n[r+1]),this._$AH[r]=a}o&&!s&&this.j(t)}j(t){t===qt?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class ie extends ee{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===qt?void 0:t}}class se extends ee{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==qt)}}class ne extends ee{constructor(t,e,i,s,n){super(t,e,i,s,n),this.type=5}_$AI(t,e=this){if((t=Gt(this,t,e,0)??qt)===Wt)return;const i=this._$AH,s=t===qt&&i!==qt||t.capture!==i.capture||t.once!==i.once||t.passive!==i.passive,n=t!==qt&&(i===qt||s);s&&this.element.removeEventListener(this.name,this,i),n&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class oe{constructor(t,e,i){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(t){Gt(this,t)}}const re=Et.litHtmlPolyfillSupport;re?.(Xt,te),(Et.litHtmlVersions??=[]).push("3.1.3");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
class ae extends V{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=((t,e,i)=>{const s=i?.renderBefore??e;let n=s._$litPart$;if(void 0===n){const t=i?.renderBefore??null;s._$litPart$=n=new te(e.insertBefore(Pt(),t),t,void 0,i??{})}return n._$AI(t),n})(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return Wt}}ae._$litElement$=!0,ae.finalized=!0,globalThis.litElementHydrateSupport?.({LitElement:ae});const he=globalThis.litElementPolyfillSupport;he?.({LitElement:ae}),(globalThis.litElementVersions??=[]).push("4.0.5");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const ce=1,le=t=>(...e)=>({_$litDirective$:t,values:e});class de{constructor(t){}get _$AU(){return this._$AM._$AU}_$AT(t,e,i){this._$Ct=t,this._$AM=e,this._$Ci=i}_$AS(t,e){return this.update(t,e)}update(t,e){return this.render(...e)}}
/**
 * @license
 * Copyright 2018 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const ue=le(class extends de{constructor(t){if(super(t),t.type!==ce||"class"!==t.name||t.strings?.length>2)throw Error("`classMap()` can only be used in the `class` attribute and must be the only part in the attribute.")}render(t){return" "+Object.keys(t).filter((e=>t[e])).join(" ")+" "}update(t,[e]){if(void 0===this.st){this.st=new Set,void 0!==t.strings&&(this.nt=new Set(t.strings.join(" ").split(/\s/).filter((t=>""!==t))));for(const t in e)e[t]&&!this.nt?.has(t)&&this.st.add(t);return this.render(e)}const i=t.element.classList;for(const t of this.st)t in e||(i.remove(t),this.st.delete(t));for(const t in e){const s=!!e[t];s===this.st.has(t)||this.nt?.has(t)||(s?(i.add(t),this.st.add(t)):(i.remove(t),this.st.delete(t)))}return lt}});
/**
 * @license
 * Copyright 2018 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const pe="unavailable",me=[..._,pe,"idle","disconnected"],ge="minimalistic-area-card",_e="ontouchstart"in window||navigator.maxTouchPoints>0||navigator.maxTouchPoints>0;class fe extends HTMLElement{constructor(){super(),this.holdTime=500,this.held=!1,this.ripple=document.createElement("mwc-ripple")}connectedCallback(){Object.assign(this.style,{position:"absolute",width:_e?"100px":"50px",height:_e?"100px":"50px",transform:"translate(-50%, -50%)",pointerEvents:"none",zIndex:"999"}),this.appendChild(this.ripple),this.ripple.primary=!0,["touchcancel","mouseout","mouseup","touchmove","mousewheel","wheel","scroll"].forEach((t=>{document.addEventListener(t,(()=>{clearTimeout(this.timer),this.stopAnimation(),this.timer=void 0}),{passive:!0})}))}bind(t,e){if(t.actionHandler)return;t.actionHandler=!0,t.addEventListener("contextmenu",(t=>{const e=t||window.event;return e.preventDefault&&e.preventDefault(),e.stopPropagation&&e.stopPropagation(),e.cancelBubble=!0,e.returnValue=!1,!1}));const i=t=>{let e,i;this.held=!1,t.touches?(e=t.touches[0].pageX,i=t.touches[0].pageY):(e=t.pageX,i=t.pageY),this.timer=window.setTimeout((()=>{this.startAnimation(e,i),this.held=!0}),this.holdTime)},s=i=>{i.preventDefault(),i.stopPropagation(),["touchend","touchcancel"].includes(i.type)&&void 0===this.timer||(clearTimeout(this.timer),this.stopAnimation(),this.timer=void 0,this.held?f(t,"action",{action:"hold"},{bubbles:!1}):e.hasDoubleClick?"click"===i.type&&i.detail<2||!this.dblClickTimeout?this.dblClickTimeout=window.setTimeout((()=>{this.dblClickTimeout=void 0,f(t,"action",{action:"tap"},{bubbles:!1})}),250):(clearTimeout(this.dblClickTimeout),this.dblClickTimeout=void 0,f(t,"action",{action:"double_tap"},{bubbles:!1})):f(t,"action",{action:"tap"},{bubbles:!1}))};t.addEventListener("touchstart",i,{passive:!0}),t.addEventListener("touchend",s),t.addEventListener("touchcancel",s),t.addEventListener("mousedown",i,{passive:!0}),t.addEventListener("click",s),t.addEventListener("keyup",(t=>{13===t.keyCode&&s(t)}))}startAnimation(t,e){Object.assign(this.style,{left:`${t}px`,top:`${e}px`,display:null}),this.ripple.disabled=!1,this.ripple.active=!0,this.ripple.unbounded=!0}stopAnimation(){this.ripple.active=!1,this.ripple.disabled=!0,this.style.display="none"}}customElements.define("action-handler-"+ge,fe);const $e=(t,e)=>{const i=(()=>{const t=document.body;if(t.querySelector("action-handler-"+ge))return t.querySelector("action-handler-"+ge);const e=document.createElement("action-handler-"+ge);return t.appendChild(e),e})();i&&i.bind(t,e)},ve=le(class extends de{update(t,[e]){return $e(t.element,e),Wt}render(t){}}),be=(t,e,i,s,n,o)=>{const r=[];(null==n?void 0:n.length)&&r.push((t=>n.includes(l(t)))),o&&r.push((e=>t.states[e]&&o(t.states[e])));const a=((t,e,i)=>{(!i||i>t.length)&&(i=t.length);const s=[];for(let n=0;n<t.length&&s.length<i;n++){let i=!0;for(const s of e)if(!s(t[n])){i=!1;break}i&&s.push(t[n])}return s})(i,r,e);if(a.length<e&&s.length){const i=be(t,e-a.length,s,[],n,o);a.push(...i)}return a};console.info("%c  Minimalistic Area Card  %c 1.2.0 ","color: orange; font-weight: bold; background: black","color: white; font-weight: bold; background: dimgray");const ye=["sensor","binary_sensor"],Ae=["fan","input_boolean","light","switch","group","automation","humidifier"];class we extends ae{constructor(){super(...arguments),this._entitiesDialog=[],this._entitiesToggle=[],this._entitiesSensor=[]}async performUpdate(){this.setArea(),this.setEntities(),await super.performUpdate()}setArea(){var t;if(null===(t=this.hass)||void 0===t?void 0:t.connected)if(this.config&&this.config.area){const t=this.hass.areas[this.config.area];t?(this.area=t,this.areaEntities=we.findAreaEntities(this.hass,t.area_id)):(this.area=void 0,this.areaEntities=void 0)}else this.area=void 0,this.areaEntities=void 0;else console.error("Invalid hass connection")}setEntities(){var t;this._entitiesDialog=[],this._entitiesToggle=[],this._entitiesSensor=[];((null===(t=this.config)||void 0===t?void 0:t.entities)||this.areaEntities||[]).forEach((t=>{var e;const i=this.parseEntity(t),[s,n]=i.entity.split(".");-1!==ye.indexOf(s)||i.attribute?this._entitiesSensor.push(i):(null===(e=this.config)||void 0===e?void 0:e.force_dialog)||-1===Ae.indexOf(s)?this._entitiesDialog.push(i):this._entitiesToggle.push(i)}))}parseEntity(t){return"string"==typeof t?{entity:t}:t}_handleEntityAction(t){const e=t.currentTarget.config;y(this,this.hass,e,t.detail.action)}_handleThisAction(t){var e,i;const s=null===(i=null===(e=t.currentTarget.getRootNode())||void 0===e?void 0:e.host)||void 0===i?void 0:i.parentElement;this.hass&&this.config&&t.detail.action&&(!s||"HUI-CARD-PREVIEW"!==s.tagName)&&y(this,this.hass,this.config,t.detail.action)}setConfig(t){if(!t||t.entities&&!Array.isArray(t.entities))throw new Error("Invalid configuration");this.config=Object.assign({hold_action:{action:"more-info"}},t)}getCardSize(){return 3}render(){var t,e;if(!this.config||!this.hass)return Vt``;const i=this.config.background_color?`background-color: ${this.config.background_color}`:"";let s;return this.config.camera_image||!this.config.image&&!(null===(t=this.area)||void 0===t?void 0:t.picture)||(s=new URL(this.config.image||(null===(e=this.area)||void 0===e?void 0:e.picture)||"",this.hass.auth.data.hassUrl).toString()),Vt`
        <ha-card @action=${this._handleThisAction} style=${i} .actionHandler=${ve({hasHold:A(this.config.hold_action),hasDoubleClick:A(this.config.double_tap_action)})}
            tabindex=${(t=>t??dt)(A(this.config.tap_action)?"0":void 0)}>
            ${s?Vt`<img src=${s} class=${ue({darken:void 0!==this.config.darken_image&&this.config.darken_image})} />`:null}
            ${this.config.camera_image?Vt`<div class=${ue({camera:!0,darken:void 0!==this.config.darken_image&&this.config.darken_image})}>
                <hui-image
                    .hass=${this.hass} 
                    .cameraImage=${this.config.camera_image} 
                    .entity=${this.config.camera_image}
                    .cameraView=${this.config.camera_view||"auto"} 
                    .width="100%"></hui-image>
            </div>`:null}
        
            <div class="box">
                <div class="card-header">${this.config.title}</div>
                <div class="sensors">
                    ${this._entitiesSensor.map((t=>this.renderEntity(t,!0,!0)))}
                </div>
                <div class="buttons">
                    ${this._entitiesDialog.map((t=>this.renderEntity(t,!0,!1)))}
                    ${this._entitiesToggle.map((t=>this.renderEntity(t,!1,!1)))}
                </div>
            </div>
        </ha-card>
    `}renderEntity(t,e,i){var s,n,o;const r=this.hass.states[t.entity],a=this.hass.entities[t.entity];if(t=Object.assign({tap_action:{action:e?"more-info":"toggle"},hold_action:{action:"more-info"},show_state:void 0===t.show_state||!!t.show_state},t),!(r&&r.state!==pe||this.config.hide_unavailable))return Vt`
            <div class="wrapper">
                <hui-warning-element .label=${h=this.hass,c=t.entity,"NOT_RUNNING"!==h.config.state?h.localize("ui.panel.lovelace.warning.entity_not_found","entity",c||"[empty]"):h.localize("ui.panel.lovelace.warning.starting")} class=${ue({shadow:void 0!==this.config.shadow&&this.config.shadow})}></hui-warning-element>
            </div>
      `;if((!r||r.state===pe)&&this.config.hide_unavailable)return Vt``;var h,c;const l=r&&r.state&&-1===me.indexOf(r.state.toString().toLowerCase()),d=`${(null===(s=r.attributes)||void 0===s?void 0:s.friendly_name)||r.entity_id}: ${g(null===(n=this.hass)||void 0===n?void 0:n.localize,r,null===(o=this.hass)||void 0===o?void 0:o.locale)}`;return Vt`
    <div class="wrapper">
        <ha-icon-button @action=${this._handleEntityAction} .actionHandler=${ve({hasHold:A(t.hold_action),hasDoubleClick:A(t.double_tap_action)})}
            .config=${t} class=${ue({"state-on":l})}>
            <state-badge .hass=${this.hass} .stateObj=${r} .title=${d} .overrideIcon=${t.icon}
                .stateColor=${void 0!==t.state_color?t.state_color:void 0===this.config.state_color||this.config.state_color} class=${ue({shadow:void 0!==this.config.shadow&&this.config.shadow})}></state-badge>
        </ha-icon-button>
        ${i&&t.show_state?Vt`
        <div class="state">
            ${t.attribute?Vt`
            ${t.prefix}
            ${r.attributes[t.attribute]}
            ${t.suffix}
            `:this.computeStateValue(r,a)}
        </div>
        `:null}
    </div>
    `}isNumericState(t){return!!t.attributes.unit_of_measurement||!!t.attributes.state_class}computeStateValue(t,e){const[i,s]=t.entity_id.split(".");if(this.isNumericState(t)){const i=Number(t.state);if(isNaN(i))return null;{const s=this.getNumberFormatOptions(t,e);return`${this.formatNumber(i,this.hass.locale,s)}${t.attributes.unit_of_measurement?" "+t.attributes.unit_of_measurement:""}`}}return"binary_sensor"!==i&&"unavailable"!==t.state&&"idle"!==t.state?t.state:null}getNumberFormatOptions(t,e){var i;const s=null==e?void 0:e.display_precision;return null!=s?{maximumFractionDigits:s,minimumFractionDigits:s}:Number.isInteger(Number(null===(i=t.attributes)||void 0===i?void 0:i.step))&&Number.isInteger(Number(t.state))?{maximumFractionDigits:0}:void 0}formatNumber(e,i,s){const n=i?d(i):void 0;if(Number.isNaN=Number.isNaN||function t(e){return"number"==typeof e&&t(e)},(null==i?void 0:i.number_format)!==t.none&&!Number.isNaN(Number(e))&&Intl)try{return new Intl.NumberFormat(n,this.getDefaultFormatOptions(e,s)).format(Number(e))}catch(t){return console.error(t),new Intl.NumberFormat(void 0,this.getDefaultFormatOptions(e,s)).format(Number(e))}return"string"==typeof e?e:`${u(e,null==s?void 0:s.maximumFractionDigits).toString()}${"currency"===(null==s?void 0:s.style)?` ${s.currency}`:""}`}getDefaultFormatOptions(t,e){const i=Object.assign({maximumFractionDigits:2},e);if("string"!=typeof t)return i;if(!e||void 0===e.minimumFractionDigits&&void 0===e.maximumFractionDigits){const e=t.indexOf(".")>-1?t.split(".")[1].length:0;i.minimumFractionDigits=e,i.maximumFractionDigits=e}return i}shouldUpdate(t){if(function(t,e,i){if(e.has("config")||i)return!0;if(t.config.entity){var s=e.get("hass");return!s||s.states[t.config.entity]!==t.hass.states[t.config.entity]}return!1}(this,t,!1))return!0;const e=t.get("hass");if(!e||e.themes!==this.hass.themes||e.locale!==this.hass.locale)return!0;for(const t of[...this._entitiesDialog,...this._entitiesToggle,...this._entitiesSensor])if(e.states[t.entity]!==this.hass.states[t.entity])return!0;return!1}static findAreaEntities(t,e){const i=t.areas&&t.areas[e],s=t.entities&&i&&Object.keys(t.entities).filter((e=>{var s;return!(t.entities[e].disabled_by||t.entities[e].hidden||"diagnostic"===t.entities[e].entity_category||"config"===t.entities[e].entity_category||t.entities[e].area_id!==i.area_id&&(null===(s=t.devices[t.entities[e].device_id||""])||void 0===s?void 0:s.area_id)!==i.area_id)})).map((t=>t));return s}static getStubConfig(t,e,i){const s=t.areas&&t.areas[Object.keys(t.areas)[0]],n=we.findAreaEntities(t,s.area_id),o={title:"Kitchen",image:"https://demo.home-assistant.io/stub_config/kitchen.png",area:"",hide_unavailable:!1,tap_action:{action:"navigate",navigation_path:"/lovelace-kitchen"},entities:[...be(t,2,(null==n?void 0:n.length)?n:e,i,["light"]),...be(t,2,(null==n?void 0:n.length)?n:e,i,["switch"]),...be(t,2,(null==n?void 0:n.length)?n:e,i,["sensor"]),...be(t,2,(null==n?void 0:n.length)?n:e,i,["binary_sensor"])]};return s?(o.area=s.area_id,o.title=s.name,o.tap_action.navigation_path="/config/areas/area/"+s.area_id,delete o.image):delete o.area,o}static get styles(){return C`
      * {
        box-sizing: border-box;
      }
      ha-card {
        position: relative;
        min-height: 48px;
        height: 100%;
        z-index: 0;
      }

      img {
          display: block;
          height: 100%;
          width: 100%;
          
          object-fit: cover;

          position: absolute;
          z-index: -1;
          pointer-events: none;
          border-radius: var(--ha-card-border-radius, 12px)
      }

      .darken {
        filter: brightness(0.55);
      }

      div.camera {
          height: 100%;
          width: 100%;
          overflow: hidden;
         
          position: absolute; 
          left: 0; top: 0; 
          
          z-index: -1;
          pointer-events: none;
          border-radius: var(--ha-card-border-radius, 12px);
      }

      div.camera hui-image {
          position: relative; 
          top: 50%;
          transform: translateY(-50%);
      }

      .box {
        text-shadow: 1px 1px 2px black;
        background-color: transparent;

        display: flex;
        flex-flow: column nowrap;
        justify-content: flex-start;

        width: 100%; height: 100%;

        padding: 0;
        font-size: 14px;
        color: var(--ha-picture-card-text-color, white);
        z-index: 1;
      }

      .box .card-header {
        padding: 10px 15px;
        font-weight: bold;
        font-size: 1.2em;
      }

      .box .sensors {
          margin-top: -8px;
          margin-bottom: -8px;
          min-height: var(--minimalistic-area-card-sensors-min-height, 10px);
          margin-left: 5px;
          font-size: 0.9em;
          line-height: 13px;
      }

      .box .buttons {
          display: block;
          background-color: var( --ha-picture-card-background-color, rgba(0, 0, 0, 0.1) );
          background-color: transparent;
          text-align: right;
          padding-top: 10px;
          padding-bottom: 10px;
          min-height: 10px;
          width: 100%;

          margin-top:auto;
      }

      .box .buttons ha-icon-button {
            margin-left: -8px;
            margin-right: -6px;
      }
      .box .sensors ha-icon-button {
            -moz-transform: scale(0.67);
            zoom: 0.67;
            vertical-align: middle;
      }
    
      .box .wrapper {
          display: inline-block;
          vertical-align: middle;
          margin-bottom: -8px;
      }
      .box ha-icon-button state-badge {
          line-height: 0px;
          color: var(--ha-picture-icon-button-color, #a9a9a9);
      }
      .box ha-icon-button state-badge.shadow {
          filter: drop-shadow(2px 2px 2px gray);
      }
      .box ha-icon-button.state-on state-badge {
          color: var(--ha-picture-icon-button-on-color, white);
      }

      .box .sensors .wrapper > * {
          display: inline-block;
          vertical-align: middle;
      }
      .box .sensors .state {
          margin-left: -9px;
      }

      .box .wrapper hui-warning-element {
          display: block;
      }
      .box .wrapper hui-warning-element.shadow {
          filter: drop-shadow(2px 2px 2px gray);
      }
    `}}we.properties={hass:{attribute:!1},config:{state:!0}},customElements.define(ge,we);const xe=window;xe.customCards=xe.customCards||[],xe.customCards.push({type:ge,name:"Minimalistic Area",preview:!0,description:"Minimalistic Area Card"});
