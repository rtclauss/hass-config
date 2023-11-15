var t,e,i=function(t,e){return n(e).format(t)},n=function(t){return new Intl.DateTimeFormat(t.language,{year:"numeric",month:"long",day:"numeric"})};!function(t){t.language="language",t.system="system",t.comma_decimal="comma_decimal",t.decimal_comma="decimal_comma",t.space_comma="space_comma",t.none="none"}(t||(t={})),function(t){t.language="language",t.system="system",t.am_pm="12",t.twenty_four="24"}(e||(e={}));var s=function(t){if(t.time_format===e.language||t.time_format===e.system){var i=t.time_format===e.language?t.language:void 0,n=(new Date).toLocaleString(i);return n.includes("AM")||n.includes("PM")}return t.time_format===e.am_pm},o=function(t,e){return r(e).format(t)},r=function(t){return new Intl.DateTimeFormat(t.language,{year:"numeric",month:"long",day:"numeric",hour:s(t)?"numeric":"2-digit",minute:"2-digit",hour12:s(t)})},a=function(t,e){return l(e).format(t)},l=function(t){return new Intl.DateTimeFormat(t.language,{hour:"numeric",minute:"2-digit",hour12:s(t)})};function c(){return(c=Object.assign||function(t){for(var e=1;e<arguments.length;e++){var i=arguments[e];for(var n in i)Object.prototype.hasOwnProperty.call(i,n)&&(t[n]=i[n])}return t}).apply(this,arguments)}function h(t){return t.substr(0,t.indexOf("."))}var d=function(e,i,n){var s=i?function(e){switch(e.number_format){case t.comma_decimal:return["en-US","en"];case t.decimal_comma:return["de","es","it"];case t.space_comma:return["fr","sv","cs"];case t.system:return;default:return e.language}}(i):void 0;if(Number.isNaN=Number.isNaN||function t(e){return"number"==typeof e&&t(e)},(null==i?void 0:i.number_format)!==t.none&&!Number.isNaN(Number(e))&&Intl)try{return new Intl.NumberFormat(s,u(e,n)).format(Number(e))}catch(t){return console.error(t),new Intl.NumberFormat(void 0,u(e,n)).format(Number(e))}return"string"==typeof e?e:function(t,e){return void 0===e&&(e=2),Math.round(t*Math.pow(10,e))/Math.pow(10,e)}(e,null==n?void 0:n.maximumFractionDigits).toString()+("currency"===(null==n?void 0:n.style)?" "+n.currency:"")},u=function(t,e){var i=c({maximumFractionDigits:2},e);if("string"!=typeof t)return i;if(!e||!e.minimumFractionDigits&&!e.maximumFractionDigits){var n=t.indexOf(".")>-1?t.split(".")[1].length:0;i.minimumFractionDigits=n,i.maximumFractionDigits=n}return i},p=function(t,e,n,s){var r=void 0!==s?s:e.state;if("unknown"===r||"unavailable"===r)return t("state.default."+r);if(function(t){return!!t.attributes.unit_of_measurement||!!t.attributes.state_class}(e)){if("monetary"===e.attributes.device_class)try{return d(r,n,{style:"currency",currency:e.attributes.unit_of_measurement})}catch(t){}return d(r,n)+(e.attributes.unit_of_measurement?" "+e.attributes.unit_of_measurement:"")}var l=function(t){return h(t.entity_id)}(e);if("input_datetime"===l){var c;if(void 0===s)return e.attributes.has_date&&e.attributes.has_time?(c=new Date(e.attributes.year,e.attributes.month-1,e.attributes.day,e.attributes.hour,e.attributes.minute),o(c,n)):e.attributes.has_date?(c=new Date(e.attributes.year,e.attributes.month-1,e.attributes.day),i(c,n)):e.attributes.has_time?((c=new Date).setHours(e.attributes.hour,e.attributes.minute),a(c,n)):e.state;try{var u=s.split(" ");if(2===u.length)return o(new Date(u.join("T")),n);if(1===u.length){if(s.includes("-"))return i(new Date(s+"T00:00"),n);if(s.includes(":")){var p=new Date;return a(new Date(p.toISOString().split("T")[0]+"T"+s),n)}}return s}catch(t){return s}}return"humidifier"===l&&"on"===r&&e.attributes.humidity?e.attributes.humidity+" %":"counter"===l||"number"===l||"input_number"===l?d(r,n):e.attributes.device_class&&t("component."+l+".state."+e.attributes.device_class+"."+r)||t("component."+l+".state._."+r)||r},m=["closed","locked","off"],v=function(t,e,i,n){n=n||{},i=null==i?{}:i;var s=new Event(e,{bubbles:void 0===n.bubbles||n.bubbles,cancelable:Boolean(n.cancelable),composed:void 0===n.composed||n.composed});return s.detail=i,t.dispatchEvent(s),s},g=function(t){v(window,"haptic",t)},f=function(t,e){return function(t,e,i){void 0===i&&(i=!0);var n,s=h(e),o="group"===s?"homeassistant":s;switch(s){case"lock":n=i?"unlock":"lock";break;case"cover":n=i?"open_cover":"close_cover";break;default:n=i?"turn_on":"turn_off"}return t.callService(o,n,{entity_id:e})}(t,e,m.includes(t.states[e].state))},_=function(t,e,i,n){if(n||(n={action:"more-info"}),!n.confirmation||n.confirmation.exemptions&&n.confirmation.exemptions.some((function(t){return t.user===e.user.id}))||(g("warning"),confirm(n.confirmation.text||"Are you sure you want to "+n.action+"?")))switch(n.action){case"more-info":(i.entity||i.camera_image)&&v(t,"hass-more-info",{entityId:i.entity?i.entity:i.camera_image});break;case"navigate":n.navigation_path&&function(t,e,i){void 0===i&&(i=!1),i?history.replaceState(null,"",e):history.pushState(null,"",e),v(window,"location-changed",{replace:i})}(0,n.navigation_path);break;case"url":n.url_path&&window.open(n.url_path);break;case"toggle":i.entity&&(f(e,i.entity),g("success"));break;case"call-service":if(!n.service)return void g("failure");var s=n.service.split(".",2);e.callService(s[0],s[1],n.service_data,n.target),g("success");break;case"fire-dom-event":v(t,"ll-custom",n)}},b=function(t,e,i,n){var s;"double_tap"===n&&i.double_tap_action?s=i.double_tap_action:"hold"===n&&i.hold_action?s=i.hold_action:"tap"===n&&i.tap_action&&(s=i.tap_action),_(t,e,i,s)};function $(t){return void 0!==t&&"none"!==t.action}
/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const y=window,A=y.ShadowRoot&&(void 0===y.ShadyCSS||y.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,w=Symbol(),x=new WeakMap;class E{constructor(t,e,i){if(this._$cssResult$=!0,i!==w)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const e=this.t;if(A&&void 0===t){const i=void 0!==e&&1===e.length;i&&(t=x.get(e)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),i&&x.set(e,t))}return t}toString(){return this.cssText}}const S=(t,...e)=>{const i=1===t.length?t[0]:e.reduce(((e,i,n)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+t[n+1]),t[0]);return new E(i,t,w)},C=A?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const i of t.cssRules)e+=i.cssText;return(t=>new E("string"==typeof t?t:t+"",void 0,w))(e)})(t):t
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */;var k;const T=window,N=T.trustedTypes,U=N?N.emptyScript:"",O=T.reactiveElementPolyfillSupport,P={toAttribute(t,e){switch(e){case Boolean:t=t?U:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let i=t;switch(e){case Boolean:i=null!==t;break;case Number:i=null===t?null:Number(t);break;case Object:case Array:try{i=JSON.parse(t)}catch(t){i=null}}return i}},H=(t,e)=>e!==t&&(e==e||t==t),D={attribute:!0,type:String,converter:P,reflect:!1,hasChanged:H};class M extends HTMLElement{constructor(){super(),this._$Ei=new Map,this.isUpdatePending=!1,this.hasUpdated=!1,this._$El=null,this.u()}static addInitializer(t){var e;this.finalize(),(null!==(e=this.h)&&void 0!==e?e:this.h=[]).push(t)}static get observedAttributes(){this.finalize();const t=[];return this.elementProperties.forEach(((e,i)=>{const n=this._$Ep(i,e);void 0!==n&&(this._$Ev.set(n,i),t.push(n))})),t}static createProperty(t,e=D){if(e.state&&(e.attribute=!1),this.finalize(),this.elementProperties.set(t,e),!e.noAccessor&&!this.prototype.hasOwnProperty(t)){const i="symbol"==typeof t?Symbol():"__"+t,n=this.getPropertyDescriptor(t,i,e);void 0!==n&&Object.defineProperty(this.prototype,t,n)}}static getPropertyDescriptor(t,e,i){return{get(){return this[e]},set(n){const s=this[t];this[e]=n,this.requestUpdate(t,s,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)||D}static finalize(){if(this.hasOwnProperty("finalized"))return!1;this.finalized=!0;const t=Object.getPrototypeOf(this);if(t.finalize(),void 0!==t.h&&(this.h=[...t.h]),this.elementProperties=new Map(t.elementProperties),this._$Ev=new Map,this.hasOwnProperty("properties")){const t=this.properties,e=[...Object.getOwnPropertyNames(t),...Object.getOwnPropertySymbols(t)];for(const i of e)this.createProperty(i,t[i])}return this.elementStyles=this.finalizeStyles(this.styles),!0}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const i=new Set(t.flat(1/0).reverse());for(const t of i)e.unshift(C(t))}else void 0!==t&&e.push(C(t));return e}static _$Ep(t,e){const i=e.attribute;return!1===i?void 0:"string"==typeof i?i:"string"==typeof t?t.toLowerCase():void 0}u(){var t;this._$E_=new Promise((t=>this.enableUpdating=t)),this._$AL=new Map,this._$Eg(),this.requestUpdate(),null===(t=this.constructor.h)||void 0===t||t.forEach((t=>t(this)))}addController(t){var e,i;(null!==(e=this._$ES)&&void 0!==e?e:this._$ES=[]).push(t),void 0!==this.renderRoot&&this.isConnected&&(null===(i=t.hostConnected)||void 0===i||i.call(t))}removeController(t){var e;null===(e=this._$ES)||void 0===e||e.splice(this._$ES.indexOf(t)>>>0,1)}_$Eg(){this.constructor.elementProperties.forEach(((t,e)=>{this.hasOwnProperty(e)&&(this._$Ei.set(e,this[e]),delete this[e])}))}createRenderRoot(){var t;const e=null!==(t=this.shadowRoot)&&void 0!==t?t:this.attachShadow(this.constructor.shadowRootOptions);return((t,e)=>{A?t.adoptedStyleSheets=e.map((t=>t instanceof CSSStyleSheet?t:t.styleSheet)):e.forEach((e=>{const i=document.createElement("style"),n=y.litNonce;void 0!==n&&i.setAttribute("nonce",n),i.textContent=e.cssText,t.appendChild(i)}))})(e,this.constructor.elementStyles),e}connectedCallback(){var t;void 0===this.renderRoot&&(this.renderRoot=this.createRenderRoot()),this.enableUpdating(!0),null===(t=this._$ES)||void 0===t||t.forEach((t=>{var e;return null===(e=t.hostConnected)||void 0===e?void 0:e.call(t)}))}enableUpdating(t){}disconnectedCallback(){var t;null===(t=this._$ES)||void 0===t||t.forEach((t=>{var e;return null===(e=t.hostDisconnected)||void 0===e?void 0:e.call(t)}))}attributeChangedCallback(t,e,i){this._$AK(t,i)}_$EO(t,e,i=D){var n;const s=this.constructor._$Ep(t,i);if(void 0!==s&&!0===i.reflect){const o=(void 0!==(null===(n=i.converter)||void 0===n?void 0:n.toAttribute)?i.converter:P).toAttribute(e,i.type);this._$El=t,null==o?this.removeAttribute(s):this.setAttribute(s,o),this._$El=null}}_$AK(t,e){var i;const n=this.constructor,s=n._$Ev.get(t);if(void 0!==s&&this._$El!==s){const t=n.getPropertyOptions(s),o="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==(null===(i=t.converter)||void 0===i?void 0:i.fromAttribute)?t.converter:P;this._$El=s,this[s]=o.fromAttribute(e,t.type),this._$El=null}}requestUpdate(t,e,i){let n=!0;void 0!==t&&(((i=i||this.constructor.getPropertyOptions(t)).hasChanged||H)(this[t],e)?(this._$AL.has(t)||this._$AL.set(t,e),!0===i.reflect&&this._$El!==t&&(void 0===this._$EC&&(this._$EC=new Map),this._$EC.set(t,i))):n=!1),!this.isUpdatePending&&n&&(this._$E_=this._$Ej())}async _$Ej(){this.isUpdatePending=!0;try{await this._$E_}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){var t;if(!this.isUpdatePending)return;this.hasUpdated,this._$Ei&&(this._$Ei.forEach(((t,e)=>this[e]=t)),this._$Ei=void 0);let e=!1;const i=this._$AL;try{e=this.shouldUpdate(i),e?(this.willUpdate(i),null===(t=this._$ES)||void 0===t||t.forEach((t=>{var e;return null===(e=t.hostUpdate)||void 0===e?void 0:e.call(t)})),this.update(i)):this._$Ek()}catch(t){throw e=!1,this._$Ek(),t}e&&this._$AE(i)}willUpdate(t){}_$AE(t){var e;null===(e=this._$ES)||void 0===e||e.forEach((t=>{var e;return null===(e=t.hostUpdated)||void 0===e?void 0:e.call(t)})),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$Ek(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$E_}shouldUpdate(t){return!0}update(t){void 0!==this._$EC&&(this._$EC.forEach(((t,e)=>this._$EO(e,this[e],t))),this._$EC=void 0),this._$Ek()}updated(t){}firstUpdated(t){}}
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
var R;M.finalized=!0,M.elementProperties=new Map,M.elementStyles=[],M.shadowRootOptions={mode:"open"},null==O||O({ReactiveElement:M}),(null!==(k=T.reactiveElementVersions)&&void 0!==k?k:T.reactiveElementVersions=[]).push("1.6.1");const j=window,z=j.trustedTypes,I=z?z.createPolicy("lit-html",{createHTML:t=>t}):void 0,L="$lit$",B=`lit$${(Math.random()+"").slice(9)}$`,V="?"+B,F=`<${V}>`,W=document,q=()=>W.createComment(""),K=t=>null===t||"object"!=typeof t&&"function"!=typeof t,Y=Array.isArray,J="[ \t\n\f\r]",X=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Z=/-->/g,G=/>/g,Q=RegExp(`>|${J}(?:([^\\s"'>=/]+)(${J}*=${J}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),tt=/'/g,et=/"/g,it=/^(?:script|style|textarea|title)$/i,nt=(t=>(e,...i)=>({_$litType$:t,strings:e,values:i}))(1),st=Symbol.for("lit-noChange"),ot=Symbol.for("lit-nothing"),rt=new WeakMap,at=W.createTreeWalker(W,129,null,!1),lt=(t,e)=>{const i=t.length-1,n=[];let s,o=2===e?"<svg>":"",r=X;for(let e=0;e<i;e++){const i=t[e];let a,l,c=-1,h=0;for(;h<i.length&&(r.lastIndex=h,l=r.exec(i),null!==l);)h=r.lastIndex,r===X?"!--"===l[1]?r=Z:void 0!==l[1]?r=G:void 0!==l[2]?(it.test(l[2])&&(s=RegExp("</"+l[2],"g")),r=Q):void 0!==l[3]&&(r=Q):r===Q?">"===l[0]?(r=null!=s?s:X,c=-1):void 0===l[1]?c=-2:(c=r.lastIndex-l[2].length,a=l[1],r=void 0===l[3]?Q:'"'===l[3]?et:tt):r===et||r===tt?r=Q:r===Z||r===G?r=X:(r=Q,s=void 0);const d=r===Q&&t[e+1].startsWith("/>")?" ":"";o+=r===X?i+F:c>=0?(n.push(a),i.slice(0,c)+L+i.slice(c)+B+d):i+B+(-2===c?(n.push(void 0),e):d)}const a=o+(t[i]||"<?>")+(2===e?"</svg>":"");if(!Array.isArray(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return[void 0!==I?I.createHTML(a):a,n]};class ct{constructor({strings:t,_$litType$:e},i){let n;this.parts=[];let s=0,o=0;const r=t.length-1,a=this.parts,[l,c]=lt(t,e);if(this.el=ct.createElement(l,i),at.currentNode=this.el.content,2===e){const t=this.el.content,e=t.firstChild;e.remove(),t.append(...e.childNodes)}for(;null!==(n=at.nextNode())&&a.length<r;){if(1===n.nodeType){if(n.hasAttributes()){const t=[];for(const e of n.getAttributeNames())if(e.endsWith(L)||e.startsWith(B)){const i=c[o++];if(t.push(e),void 0!==i){const t=n.getAttribute(i.toLowerCase()+L).split(B),e=/([.?@])?(.*)/.exec(i);a.push({type:1,index:s,name:e[2],strings:t,ctor:"."===e[1]?mt:"?"===e[1]?gt:"@"===e[1]?ft:pt})}else a.push({type:6,index:s})}for(const e of t)n.removeAttribute(e)}if(it.test(n.tagName)){const t=n.textContent.split(B),e=t.length-1;if(e>0){n.textContent=z?z.emptyScript:"";for(let i=0;i<e;i++)n.append(t[i],q()),at.nextNode(),a.push({type:2,index:++s});n.append(t[e],q())}}}else if(8===n.nodeType)if(n.data===V)a.push({type:2,index:s});else{let t=-1;for(;-1!==(t=n.data.indexOf(B,t+1));)a.push({type:7,index:s}),t+=B.length-1}s++}}static createElement(t,e){const i=W.createElement("template");return i.innerHTML=t,i}}function ht(t,e,i=t,n){var s,o,r,a;if(e===st)return e;let l=void 0!==n?null===(s=i._$Co)||void 0===s?void 0:s[n]:i._$Cl;const c=K(e)?void 0:e._$litDirective$;return(null==l?void 0:l.constructor)!==c&&(null===(o=null==l?void 0:l._$AO)||void 0===o||o.call(l,!1),void 0===c?l=void 0:(l=new c(t),l._$AT(t,i,n)),void 0!==n?(null!==(r=(a=i)._$Co)&&void 0!==r?r:a._$Co=[])[n]=l:i._$Cl=l),void 0!==l&&(e=ht(t,l._$AS(t,e.values),l,n)),e}class dt{constructor(t,e){this.u=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}v(t){var e;const{el:{content:i},parts:n}=this._$AD,s=(null!==(e=null==t?void 0:t.creationScope)&&void 0!==e?e:W).importNode(i,!0);at.currentNode=s;let o=at.nextNode(),r=0,a=0,l=n[0];for(;void 0!==l;){if(r===l.index){let e;2===l.type?e=new ut(o,o.nextSibling,this,t):1===l.type?e=new l.ctor(o,l.name,l.strings,this,t):6===l.type&&(e=new _t(o,this,t)),this.u.push(e),l=n[++a]}r!==(null==l?void 0:l.index)&&(o=at.nextNode(),r++)}return s}p(t){let e=0;for(const i of this.u)void 0!==i&&(void 0!==i.strings?(i._$AI(t,i,e),e+=i.strings.length-2):i._$AI(t[e])),e++}}class ut{constructor(t,e,i,n){var s;this.type=2,this._$AH=ot,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=i,this.options=n,this._$Cm=null===(s=null==n?void 0:n.isConnected)||void 0===s||s}get _$AU(){var t,e;return null!==(e=null===(t=this._$AM)||void 0===t?void 0:t._$AU)&&void 0!==e?e:this._$Cm}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===(null==t?void 0:t.nodeType)&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=ht(this,t,e),K(t)?t===ot||null==t||""===t?(this._$AH!==ot&&this._$AR(),this._$AH=ot):t!==this._$AH&&t!==st&&this.g(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>Y(t)||"function"==typeof(null==t?void 0:t[Symbol.iterator]))(t)?this.k(t):this.g(t)}S(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.S(t))}g(t){this._$AH!==ot&&K(this._$AH)?this._$AA.nextSibling.data=t:this.T(W.createTextNode(t)),this._$AH=t}$(t){var e;const{values:i,_$litType$:n}=t,s="number"==typeof n?this._$AC(t):(void 0===n.el&&(n.el=ct.createElement(n.h,this.options)),n);if((null===(e=this._$AH)||void 0===e?void 0:e._$AD)===s)this._$AH.p(i);else{const t=new dt(s,this),e=t.v(this.options);t.p(i),this.T(e),this._$AH=t}}_$AC(t){let e=rt.get(t.strings);return void 0===e&&rt.set(t.strings,e=new ct(t)),e}k(t){Y(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let i,n=0;for(const s of t)n===e.length?e.push(i=new ut(this.S(q()),this.S(q()),this,this.options)):i=e[n],i._$AI(s),n++;n<e.length&&(this._$AR(i&&i._$AB.nextSibling,n),e.length=n)}_$AR(t=this._$AA.nextSibling,e){var i;for(null===(i=this._$AP)||void 0===i||i.call(this,!1,!0,e);t&&t!==this._$AB;){const e=t.nextSibling;t.remove(),t=e}}setConnected(t){var e;void 0===this._$AM&&(this._$Cm=t,null===(e=this._$AP)||void 0===e||e.call(this,t))}}class pt{constructor(t,e,i,n,s){this.type=1,this._$AH=ot,this._$AN=void 0,this.element=t,this.name=e,this._$AM=n,this.options=s,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=ot}get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}_$AI(t,e=this,i,n){const s=this.strings;let o=!1;if(void 0===s)t=ht(this,t,e,0),o=!K(t)||t!==this._$AH&&t!==st,o&&(this._$AH=t);else{const n=t;let r,a;for(t=s[0],r=0;r<s.length-1;r++)a=ht(this,n[i+r],e,r),a===st&&(a=this._$AH[r]),o||(o=!K(a)||a!==this._$AH[r]),a===ot?t=ot:t!==ot&&(t+=(null!=a?a:"")+s[r+1]),this._$AH[r]=a}o&&!n&&this.j(t)}j(t){t===ot?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,null!=t?t:"")}}class mt extends pt{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===ot?void 0:t}}const vt=z?z.emptyScript:"";class gt extends pt{constructor(){super(...arguments),this.type=4}j(t){t&&t!==ot?this.element.setAttribute(this.name,vt):this.element.removeAttribute(this.name)}}class ft extends pt{constructor(t,e,i,n,s){super(t,e,i,n,s),this.type=5}_$AI(t,e=this){var i;if((t=null!==(i=ht(this,t,e,0))&&void 0!==i?i:ot)===st)return;const n=this._$AH,s=t===ot&&n!==ot||t.capture!==n.capture||t.once!==n.once||t.passive!==n.passive,o=t!==ot&&(n===ot||s);s&&this.element.removeEventListener(this.name,this,n),o&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){var e,i;"function"==typeof this._$AH?this._$AH.call(null!==(i=null===(e=this.options)||void 0===e?void 0:e.host)&&void 0!==i?i:this.element,t):this._$AH.handleEvent(t)}}class _t{constructor(t,e,i){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(t){ht(this,t)}}const bt=j.litHtmlPolyfillSupport;null==bt||bt(ct,ut),(null!==(R=j.litHtmlVersions)&&void 0!==R?R:j.litHtmlVersions=[]).push("2.7.0");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
var $t,yt;class At extends M{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){var t,e;const i=super.createRenderRoot();return null!==(t=(e=this.renderOptions).renderBefore)&&void 0!==t||(e.renderBefore=i.firstChild),i}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=((t,e,i)=>{var n,s;const o=null!==(n=null==i?void 0:i.renderBefore)&&void 0!==n?n:e;let r=o._$litPart$;if(void 0===r){const t=null!==(s=null==i?void 0:i.renderBefore)&&void 0!==s?s:null;o._$litPart$=r=new ut(e.insertBefore(q(),t),t,void 0,null!=i?i:{})}return r._$AI(t),r})(e,this.renderRoot,this.renderOptions)}connectedCallback(){var t;super.connectedCallback(),null===(t=this._$Do)||void 0===t||t.setConnected(!0)}disconnectedCallback(){var t;super.disconnectedCallback(),null===(t=this._$Do)||void 0===t||t.setConnected(!1)}render(){return st}}At.finalized=!0,At._$litElement$=!0,null===($t=globalThis.litElementHydrateSupport)||void 0===$t||$t.call(globalThis,{LitElement:At});const wt=globalThis.litElementPolyfillSupport;null==wt||wt({LitElement:At}),(null!==(yt=globalThis.litElementVersions)&&void 0!==yt?yt:globalThis.litElementVersions=[]).push("3.3.0");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const xt=1,Et=t=>(...e)=>({_$litDirective$:t,values:e});class St{constructor(t){}get _$AU(){return this._$AM._$AU}_$AT(t,e,i){this._$Ct=t,this._$AM=e,this._$Ci=i}_$AS(t,e){return this.update(t,e)}update(t,e){return this.render(...e)}}
/**
 * @license
 * Copyright 2018 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const Ct=Et(class extends St{constructor(t){var e;if(super(t),t.type!==xt||"class"!==t.name||(null===(e=t.strings)||void 0===e?void 0:e.length)>2)throw Error("`classMap()` can only be used in the `class` attribute and must be the only part in the attribute.")}render(t){return" "+Object.keys(t).filter((e=>t[e])).join(" ")+" "}update(t,[e]){var i,n;if(void 0===this.nt){this.nt=new Set,void 0!==t.strings&&(this.st=new Set(t.strings.join(" ").split(/\s/).filter((t=>""!==t))));for(const t in e)e[t]&&!(null===(i=this.st)||void 0===i?void 0:i.has(t))&&this.nt.add(t);return this.render(e)}const s=t.element.classList;this.nt.forEach((t=>{t in e||(s.remove(t),this.nt.delete(t))}));for(const t in e){const i=!!e[t];i===this.nt.has(t)||(null===(n=this.st)||void 0===n?void 0:n.has(t))||(i?(s.add(t),this.nt.add(t)):(s.remove(t),this.nt.delete(t)))}return st}});
/**
 * @license
 * Copyright 2018 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const kt="unavailable",Tt=[...m,kt,"idle","disconnected"],Nt="minimalistic-area-card",Ut="ontouchstart"in window||navigator.maxTouchPoints>0||navigator.maxTouchPoints>0;class Ot extends HTMLElement{constructor(){super(),this.holdTime=500,this.held=!1,this.ripple=document.createElement("mwc-ripple")}connectedCallback(){Object.assign(this.style,{position:"absolute",width:Ut?"100px":"50px",height:Ut?"100px":"50px",transform:"translate(-50%, -50%)",pointerEvents:"none",zIndex:"999"}),this.appendChild(this.ripple),this.ripple.primary=!0,["touchcancel","mouseout","mouseup","touchmove","mousewheel","wheel","scroll"].forEach((t=>{document.addEventListener(t,(()=>{clearTimeout(this.timer),this.stopAnimation(),this.timer=void 0}),{passive:!0})}))}bind(t,e){if(t.actionHandler)return;t.actionHandler=!0,t.addEventListener("contextmenu",(t=>{const e=t||window.event;return e.preventDefault&&e.preventDefault(),e.stopPropagation&&e.stopPropagation(),e.cancelBubble=!0,e.returnValue=!1,!1}));const i=t=>{let e,i;this.held=!1,t.touches?(e=t.touches[0].pageX,i=t.touches[0].pageY):(e=t.pageX,i=t.pageY),this.timer=window.setTimeout((()=>{this.startAnimation(e,i),this.held=!0}),this.holdTime)},n=i=>{i.preventDefault(),i.stopPropagation(),["touchend","touchcancel"].includes(i.type)&&void 0===this.timer||(clearTimeout(this.timer),this.stopAnimation(),this.timer=void 0,this.held?v(t,"action",{action:"hold"},{bubbles:!1}):e.hasDoubleClick?"click"===i.type&&i.detail<2||!this.dblClickTimeout?this.dblClickTimeout=window.setTimeout((()=>{this.dblClickTimeout=void 0,v(t,"action",{action:"tap"},{bubbles:!1})}),250):(clearTimeout(this.dblClickTimeout),this.dblClickTimeout=void 0,v(t,"action",{action:"double_tap"},{bubbles:!1})):v(t,"action",{action:"tap"},{bubbles:!1}))};t.addEventListener("touchstart",i,{passive:!0}),t.addEventListener("touchend",n),t.addEventListener("touchcancel",n),t.addEventListener("mousedown",i,{passive:!0}),t.addEventListener("click",n),t.addEventListener("keyup",(t=>{13===t.keyCode&&n(t)}))}startAnimation(t,e){Object.assign(this.style,{left:`${t}px`,top:`${e}px`,display:null}),this.ripple.disabled=!1,this.ripple.active=!0,this.ripple.unbounded=!0}stopAnimation(){this.ripple.active=!1,this.ripple.disabled=!0,this.style.display="none"}}customElements.define("action-handler-"+Nt,Ot);const Pt=(t,e)=>{const i=(()=>{const t=document.body;if(t.querySelector("action-handler-"+Nt))return t.querySelector("action-handler-"+Nt);const e=document.createElement("action-handler-"+Nt);return t.appendChild(e),e})();i&&i.bind(t,e)},Ht=Et(class extends St{update(t,[e]){return Pt(t.element,e),st}render(t){}}),Dt=(t,e,i,n,s,o)=>{const r=[];(null==s?void 0:s.length)&&r.push((t=>s.includes(h(t)))),o&&r.push((e=>t.states[e]&&o(t.states[e])));const a=((t,e,i)=>{(!i||i>t.length)&&(i=t.length);const n=[];for(let s=0;s<t.length&&n.length<i;s++){let i=!0;for(const n of e)if(!n(t[s])){i=!1;break}i&&n.push(t[s])}return n})(i,r,e);if(a.length<e&&n.length){const i=Dt(t,e-a.length,n,[],s,o);a.push(...i)}return a};console.info("%c  Minimalistic Area Card  %c 1.1.16 ","color: orange; font-weight: bold; background: black","color: white; font-weight: bold; background: dimgray");const Mt=["sensor","binary_sensor"],Rt=["fan","input_boolean","light","switch","group","automation","humidifier"];class jt extends At{constructor(){super(...arguments),this._entitiesDialog=[],this._entitiesToggle=[],this._entitiesSensor=[]}async performUpdate(){this.setArea(),this.setEntities(),await super.performUpdate()}setArea(){var t;if(null===(t=this.hass)||void 0===t?void 0:t.connected)if(this.config&&this.config.area){const t=this.hass.areas[this.config.area];t?(this.area=t,this.areaEntities=jt.findAreaEntities(this.hass,t.area_id)):(this.area=void 0,this.areaEntities=void 0)}else this.area=void 0,this.areaEntities=void 0;else console.error("Invalid hass connection")}setEntities(){var t;this._entitiesDialog=[],this._entitiesToggle=[],this._entitiesSensor=[];((null===(t=this.config)||void 0===t?void 0:t.entities)||this.areaEntities||[]).forEach((t=>{var e;const i=this.parseEntity(t),[n,s]=i.entity.split(".");-1!==Mt.indexOf(n)||i.attribute?this._entitiesSensor.push(i):(null===(e=this.config)||void 0===e?void 0:e.force_dialog)||-1===Rt.indexOf(n)?this._entitiesDialog.push(i):this._entitiesToggle.push(i)}))}parseEntity(t){return"string"==typeof t?{entity:t}:t}_handleEntityAction(t){const e=t.currentTarget.config;b(this,this.hass,e,t.detail.action)}_handleThisAction(t){var e,i;const n=null===(i=null===(e=t.currentTarget.getRootNode())||void 0===e?void 0:e.host)||void 0===i?void 0:i.parentElement;this.hass&&this.config&&t.detail.action&&(!n||"HUI-CARD-PREVIEW"!==n.tagName)&&b(this,this.hass,this.config,t.detail.action)}setConfig(t){if(!t||t.entities&&!Array.isArray(t.entities))throw new Error("Invalid configuration");this.config=Object.assign({hold_action:{action:"more-info"}},t)}getCardSize(){return 3}render(){var t,e;if(!this.config||!this.hass)return nt``;const i=this.config.background_color?`background-color: ${this.config.background_color}`:"";let n;return this.config.camera_image||!this.config.image&&!(null===(t=this.area)||void 0===t?void 0:t.picture)||(n=new URL(this.config.image||(null===(e=this.area)||void 0===e?void 0:e.picture)||"",this.hass.auth.data.hassUrl).toString()),nt`
        <ha-card @action=${this._handleThisAction} style=${i} .actionHandler=${Ht({hasHold:$(this.config.hold_action),hasDoubleClick:$(this.config.double_tap_action)})}
            tabindex=${(t=>null!=t?t:ot)($(this.config.tap_action)?"0":void 0)}>
            ${n?nt`<img src=${n} class=${Ct({darken:void 0!==this.config.darken_image&&this.config.darken_image})} />`:null}
            ${this.config.camera_image?nt`<div class=${Ct({camera:!0,darken:void 0!==this.config.darken_image&&this.config.darken_image})}>
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
    `}renderEntity(t,e,i){var n,s,o;const r=this.hass.states[t.entity];if(t=Object.assign({tap_action:{action:e?"more-info":"toggle"},hold_action:{action:"more-info"},show_state:void 0===t.show_state||!!t.show_state},t),!(r&&r.state!==kt||this.config.hide_unavailable))return nt`
            <div class="wrapper">
                <hui-warning-element .label=${a=this.hass,l=t.entity,"NOT_RUNNING"!==a.config.state?a.localize("ui.panel.lovelace.warning.entity_not_found","entity",l||"[empty]"):a.localize("ui.panel.lovelace.warning.starting")} class=${Ct({shadow:void 0!==this.config.shadow&&this.config.shadow})}></hui-warning-element>
            </div>
      `;if((!r||r.state===kt)&&this.config.hide_unavailable)return nt``;var a,l;const c=r&&r.state&&-1===Tt.indexOf(r.state.toString().toLowerCase()),h=`${(null===(n=r.attributes)||void 0===n?void 0:n.friendly_name)||r.entity_id}: ${p(null===(s=this.hass)||void 0===s?void 0:s.localize,r,null===(o=this.hass)||void 0===o?void 0:o.locale)}`;return nt`
    <div class="wrapper">
        <ha-icon-button @action=${this._handleEntityAction} .actionHandler=${Ht({hasHold:$(t.hold_action),hasDoubleClick:$(t.double_tap_action)})}
            .config=${t} class=${Ct({"state-on":c})}>
            <state-badge .hass=${this.hass} .stateObj=${r} .title=${h} .overrideIcon=${t.icon}
                .stateColor=${void 0!==t.state_color?t.state_color:void 0===this.config.state_color||this.config.state_color} class=${Ct({shadow:void 0!==this.config.shadow&&this.config.shadow})}></state-badge>
        </ha-icon-button>
        ${i&&t.show_state?nt`
        <div class="state">
            ${t.attribute?nt`
            ${t.prefix}
            ${r.attributes[t.attribute]}
            ${t.suffix}
            `:this.computeStateValue(r)}
        </div>
        `:null}
    </div>
    `}isNumericState(t){return!!t.attributes.unit_of_measurement||!!t.attributes.state_class}computeStateValue(t){const[e,i]=t.entity_id.split(".");if(this.isNumericState(t)){const e=Number(t.state);return isNaN(e)?null:`${e}${t.attributes.unit_of_measurement?" "+t.attributes.unit_of_measurement:""}`}return"binary_sensor"!==e&&"unavailable"!==t.state&&"idle"!==t.state?t.state:null}shouldUpdate(t){if(function(t,e,i){if(e.has("config")||i)return!0;if(t.config.entity){var n=e.get("hass");return!n||n.states[t.config.entity]!==t.hass.states[t.config.entity]}return!1}(this,t,!1))return!0;const e=t.get("hass");if(!e||e.themes!==this.hass.themes||e.locale!==this.hass.locale)return!0;for(const t of[...this._entitiesDialog,...this._entitiesToggle,...this._entitiesSensor])if(e.states[t.entity]!==this.hass.states[t.entity])return!0;return!1}static findAreaEntities(t,e){const i=t.areas&&t.areas[e],n=t.entities&&i&&Object.keys(t.entities).filter((e=>{var n;return!(t.entities[e].disabled_by||t.entities[e].hidden||"diagnostic"===t.entities[e].entity_category||"config"===t.entities[e].entity_category||t.entities[e].area_id!==i.area_id&&(null===(n=t.devices[t.entities[e].device_id||""])||void 0===n?void 0:n.area_id)!==i.area_id)})).map((t=>t));return n}static getStubConfig(t,e,i){const n=t.areas&&t.areas[Object.keys(t.areas)[0]],s=jt.findAreaEntities(t,n.area_id),o={title:"Kitchen",image:"https://demo.home-assistant.io/stub_config/kitchen.png",area:"",hide_unavailable:!1,tap_action:{action:"navigate",navigation_path:"/lovelace-kitchen"},entities:[...Dt(t,2,(null==s?void 0:s.length)?s:e,i,["light"]),...Dt(t,2,(null==s?void 0:s.length)?s:e,i,["switch"]),...Dt(t,2,(null==s?void 0:s.length)?s:e,i,["sensor"]),...Dt(t,2,(null==s?void 0:s.length)?s:e,i,["binary_sensor"])]};return n?(o.area=n.area_id,o.title=n.name,o.tap_action.navigation_path="/config/areas/area/"+n.area_id,delete o.image):delete o.area,o}static get styles(){return S`
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
    `}}jt.properties={hass:{attribute:!1},config:{state:!0}},customElements.define(Nt,jt);const zt=window;zt.customCards=zt.customCards||[],zt.customCards.push({type:Nt,name:"Minimalistic Area",preview:!0,description:"Minimalistic Area Card"});
