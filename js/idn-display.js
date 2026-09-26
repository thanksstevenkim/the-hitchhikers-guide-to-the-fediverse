/*
 * Punycode decoding logic adapted from Punycode.js v2.3.1.
 * Copyright Mathias Bynens <https://mathiasbynens.be/>
 * Released under the MIT license; see idn-display.LICENSE.txt.
 */
(function attachIdnDisplay(global) {
  "use strict";

  const MAX_INT = 2147483647;
  const BASE = 36;
  const T_MIN = 1;
  const T_MAX = 26;
  const SKEW = 38;
  const DAMP = 700;
  const INITIAL_BIAS = 72;
  const INITIAL_N = 128;
  const DELIMITER = "-";

  function fail(message) {
    throw new RangeError(message);
  }

  function basicToDigit(codePoint) {
    if (codePoint >= 0x30 && codePoint < 0x3a) {
      return 26 + (codePoint - 0x30);
    }
    if (codePoint >= 0x41 && codePoint < 0x5b) {
      return codePoint - 0x41;
    }
    if (codePoint >= 0x61 && codePoint < 0x7b) {
      return codePoint - 0x61;
    }
    return BASE;
  }

  function adapt(delta, pointCount, isFirstTime) {
    let offset = 0;
    delta = isFirstTime ? Math.floor(delta / DAMP) : delta >> 1;
    delta += Math.floor(delta / pointCount);

    while (delta > ((BASE - T_MIN) * T_MAX) >> 1) {
      delta = Math.floor(delta / (BASE - T_MIN));
      offset += BASE;
    }

    return Math.floor(
      offset + ((BASE - T_MIN + 1) * delta) / (delta + SKEW)
    );
  }

  function decodeLabel(input) {
    const output = [];
    let index = 0;
    let codePoint = INITIAL_N;
    let bias = INITIAL_BIAS;
    let basicLength = input.lastIndexOf(DELIMITER);

    if (basicLength < 0) {
      basicLength = 0;
    }

    for (let cursor = 0; cursor < basicLength; cursor += 1) {
      const basicCodePoint = input.charCodeAt(cursor);
      if (basicCodePoint >= 0x80) {
        fail("Invalid Punycode label");
      }
      output.push(basicCodePoint);
    }

    index = basicLength > 0 ? basicLength + 1 : 0;
    let insertionIndex = 0;

    while (index < input.length) {
      const previousInsertionIndex = insertionIndex;
      let weight = 1;

      for (let thresholdOffset = BASE; ; thresholdOffset += BASE) {
        if (index >= input.length) {
          fail("Invalid Punycode label");
        }

        const digit = basicToDigit(input.charCodeAt(index));
        index += 1;
        if (digit >= BASE) {
          fail("Invalid Punycode label");
        }
        if (digit > Math.floor((MAX_INT - insertionIndex) / weight)) {
          fail("Punycode label overflow");
        }

        insertionIndex += digit * weight;
        const threshold =
          thresholdOffset <= bias
            ? T_MIN
            : thresholdOffset >= bias + T_MAX
              ? T_MAX
              : thresholdOffset - bias;

        if (digit < threshold) {
          break;
        }

        const baseMinusThreshold = BASE - threshold;
        if (weight > Math.floor(MAX_INT / baseMinusThreshold)) {
          fail("Punycode label overflow");
        }
        weight *= baseMinusThreshold;
      }

      const outputLength = output.length + 1;
      bias = adapt(
        insertionIndex - previousInsertionIndex,
        outputLength,
        previousInsertionIndex === 0
      );

      if (Math.floor(insertionIndex / outputLength) > MAX_INT - codePoint) {
        fail("Punycode label overflow");
      }

      codePoint += Math.floor(insertionIndex / outputLength);
      insertionIndex %= outputLength;
      output.splice(insertionIndex, 0, codePoint);
      insertionIndex += 1;
    }

    return String.fromCodePoint(...output);
  }

  function toUnicodeHostname(hostname) {
    if (typeof hostname !== "string" || !/(^|\.)xn--/i.test(hostname)) {
      return hostname;
    }

    try {
      return hostname
        .split(".")
        .map((label) => {
          if (!/^xn--/i.test(label)) {
            return label;
          }
          const decodedLabel = decodeLabel(label.slice(4).toLowerCase());
          if (!/[^\x00-\x7f]/.test(decodedLabel)) {
            fail("Invalid internationalized label");
          }
          return decodedLabel;
        })
        .join(".");
    } catch (error) {
      return hostname;
    }
  }

  global.hitchhikerIdn = Object.freeze({ toUnicodeHostname });
})(globalThis);
