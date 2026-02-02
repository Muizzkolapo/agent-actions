import { describe, it, expect } from 'vitest';
import { snakeToCamel, transformKeys, getString, getNumber, getObject } from './caseTransform';

describe('snakeToCamel', () => {
    it('converts snake_case to camelCase', () => {
        expect(snakeToCamel('total_count')).toBe('totalCount');
        expect(snakeToCamel('db_size_bytes')).toBe('dbSizeBytes');
        expect(snakeToCamel('node_name')).toBe('nodeName');
    });

    it('handles single words', () => {
        expect(snakeToCamel('count')).toBe('count');
        expect(snakeToCamel('name')).toBe('name');
    });

    it('handles empty string', () => {
        expect(snakeToCamel('')).toBe('');
    });
});

describe('transformKeys', () => {
    it('transforms object keys', () => {
        const input = { total_count: 10, node_name: 'foo' };
        expect(transformKeys(input)).toEqual({ totalCount: 10, nodeName: 'foo' });
    });

    it('handles nested objects', () => {
        const input = { outer_key: { inner_key: 'value' } };
        expect(transformKeys(input)).toEqual({ outerKey: { innerKey: 'value' } });
    });

    it('handles arrays', () => {
        const input = [{ item_name: 'a' }, { item_name: 'b' }];
        expect(transformKeys(input)).toEqual([{ itemName: 'a' }, { itemName: 'b' }]);
    });

    it('handles null and undefined', () => {
        expect(transformKeys(null)).toBe(null);
        expect(transformKeys(undefined)).toBe(undefined);
    });

    it('preserves primitives', () => {
        expect(transformKeys(42)).toBe(42);
        expect(transformKeys('string')).toBe('string');
        expect(transformKeys(true)).toBe(true);
    });
});

describe('type guards', () => {
    const data = { name: 'test', count: 42, nested: { key: 'value' } };

    it('getString returns string or fallback', () => {
        expect(getString(data, 'name')).toBe('test');
        expect(getString(data, 'missing')).toBe('');
        expect(getString(data, 'missing', 'default')).toBe('default');
        expect(getString(data, 'count')).toBe('');  // number, not string
    });

    it('getNumber returns number or fallback', () => {
        expect(getNumber(data, 'count')).toBe(42);
        expect(getNumber(data, 'missing')).toBe(0);
        expect(getNumber(data, 'missing', -1)).toBe(-1);
        expect(getNumber(data, 'name')).toBe(0);  // string, not number
    });

    it('getObject returns object or empty', () => {
        expect(getObject(data, 'nested')).toEqual({ key: 'value' });
        expect(getObject(data, 'missing')).toEqual({});
        expect(getObject(data, 'name')).toEqual({});  // string, not object
    });
});
